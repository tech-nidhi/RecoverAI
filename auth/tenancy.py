"""
RecoverAI Multi-Tenant Auth, Workspace Isolation, API Keys, and Tenancy Engine.
"""

import os
import secrets
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import uuid4

DEFAULT_WORKSPACE_ID = "ws_default"


def get_db_connection(db_path: str = "data/recover_ai.db") -> sqlite3.Connection:
    """Establishes SQLite connection with row_factory dict access and WAL mode + timeout."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tenancy_tables_and_columns_exist(db_path: str = "data/recover_ai.db") -> None:
    """
    Ensures multi-tenant infrastructure tables exist and performs backward-compatible
    auto-migrations by adding workspace_id TEXT DEFAULT 'ws_default' to pre-existing tables.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. Tenancy infrastructure tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            merchant_name TEXT NOT NULL,
            environment TEXT NOT NULL DEFAULT 'SANDBOX',
            webhook_secret TEXT NOT NULL,
            onboarding_completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'ADMIN',
            created_at TEXT NOT NULL,
            PRIMARY KEY (workspace_id, user_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            name TEXT NOT NULL,
            key_prefix TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            environment TEXT NOT NULL DEFAULT 'SANDBOX',
            created_at TEXT NOT NULL,
            revoked_at TEXT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gateway_connections (
            workspace_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'RAZORPAY',
            environment TEXT NOT NULL DEFAULT 'SANDBOX',
            status TEXT NOT NULL DEFAULT 'CONNECTED',
            key_id_masked TEXT,
            secret_masked TEXT,
            updated_at TEXT NOT NULL
        );
    """)

    conn.commit()

    # 2. Add workspace_id column to core tables if missing
    tables_to_migrate = [
        "revenue_events",
        "webhook_events",
        "action_executions",
        "governance_config",
        "governance_audit_logs",
        "approval_requests",
        "experiments"
    ]

    for table in tables_to_migrate:
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table,))
        if cursor.fetchone():
            cursor.execute(f"PRAGMA table_info({table});")
            columns = [col["name"] for col in cursor.fetchall()]
            if "workspace_id" not in columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT DEFAULT '{DEFAULT_WORKSPACE_ID}';")

    conn.commit()

    # 3. Seed default workspace and demo user for backward compatibility
    now_str = datetime.utcnow().isoformat() + "Z"
    cursor.execute("SELECT workspace_id FROM workspaces WHERE workspace_id = ?;", (DEFAULT_WORKSPACE_ID,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO workspaces (workspace_id, merchant_name, environment, webhook_secret, onboarding_completed, created_at)
            VALUES (?, ?, 'SANDBOX', ?, 1, ?);
        """, (DEFAULT_WORKSPACE_ID, "Demo Merchant Corp", "whsec_demo_secret_key_12345", now_str))

    cursor.execute("SELECT user_id FROM users WHERE email = ?;", ("demo@recoverai.io",))
    demo_user = cursor.fetchone()
    if not demo_user:
        salt = secrets.token_hex(16)
        pwd_hash = _hash_password_with_salt("password123", salt)
        demo_user_id = "user_demo_001"
        cursor.execute("""
            INSERT INTO users (user_id, email, password_hash, salt, full_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (demo_user_id, "demo@recoverai.io", pwd_hash, salt, "Demo Admin", now_str))

        cursor.execute("""
            INSERT INTO workspace_members (workspace_id, user_id, role, created_at)
            VALUES (?, ?, 'ADMIN', ?);
        """, (DEFAULT_WORKSPACE_ID, demo_user_id, now_str))

    conn.commit()
    conn.close()


def _hash_password_with_salt(password: str, salt: str) -> str:
    """Hashes password using PBKDF2-HMAC-SHA256."""
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    )
    return key.hex()


def hash_password(password: str) -> tuple[str, str]:
    """Hashes password using PBKDF2-HMAC-SHA256 with a newly generated salt."""
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password_with_salt(password, salt)
    return pwd_hash, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verifies a plain text password against stored hash and salt."""
    return secrets.compare_digest(_hash_password_with_salt(password, salt), stored_hash)


def create_merchant_user(
    email: str,
    password: str,
    full_name: str,
    merchant_name: str,
    db_path: str = "data/recover_ai.db"
) -> Dict[str, Any]:
    """
    Registers a new user, creates their merchant workspace, and returns auth session details.
    """
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    email_clean = email.strip().lower()
    cursor.execute("SELECT user_id FROM users WHERE email = ?;", (email_clean,))
    if cursor.fetchone():
        conn.close()
        raise ValueError(f"An account with email '{email_clean}' already exists.")

    user_id = f"usr_{uuid4().hex[:10]}"
    salt = secrets.token_hex(16)
    password_hash = _hash_password_with_salt(password, salt)
    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("""
        INSERT INTO users (user_id, email, password_hash, salt, full_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?);
    """, (user_id, email_clean, password_hash, salt, full_name.strip(), now_str))

    # Generate slugified workspace_id
    clean_company = "".join(c for c in merchant_name.lower().replace(" ", "_") if c.isalnum() or c == "_") or "merchant"
    workspace_id = f"ws_{clean_company}_{uuid4().hex[:6]}"
    webhook_secret = f"whsec_{secrets.token_hex(16)}"

    cursor.execute("""
        INSERT INTO workspaces (workspace_id, merchant_name, environment, webhook_secret, onboarding_completed, created_at)
        VALUES (?, ?, 'SANDBOX', ?, 0, ?);
    """, (workspace_id, merchant_name.strip(), webhook_secret, now_str))

    cursor.execute("""
        INSERT INTO workspace_members (workspace_id, user_id, role, created_at)
        VALUES (?, ?, 'ADMIN', ?);
    """, (workspace_id, user_id, now_str))

    # Create default gateway connection entry
    cursor.execute("""
        INSERT INTO gateway_connections (workspace_id, provider, environment, status, key_id_masked, secret_masked, updated_at)
        VALUES (?, 'RAZORPAY', 'SANDBOX', 'CONNECTED', 'rzp_test_••••••••', '••••••••••••••••', ?);
    """, (workspace_id, now_str))

    conn.commit()
    conn.close()

    # Create initial session
    session = create_session(user_id=user_id, workspace_id=workspace_id, db_path=db_path)
    return {
        "user_id": user_id,
        "email": email_clean,
        "full_name": full_name,
        "workspace_id": workspace_id,
        "merchant_name": merchant_name,
        "onboarding_completed": False,
        "session_token": session["session_token"],
        "expires_at": session["expires_at"],
        "user": {
            "id": user_id,
            "email": email_clean,
            "full_name": full_name
        },
        "workspace": {
            "id": workspace_id,
            "name": merchant_name,
            "environment": "SANDBOX",
            "onboarding_completed": False
        }
    }


def authenticate_user(email: str, password: str, db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """Authenticates user credentials and creates an active session."""
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    email_clean = email.strip().lower()
    cursor.execute("SELECT * FROM users WHERE email = ?;", (email_clean,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        raise ValueError("Invalid email or password.")

    user_dict = dict(user)
    if not verify_password(password, user_dict["password_hash"], user_dict["salt"]):
        conn.close()
        raise ValueError("Invalid email or password.")

    # Find primary workspace for user
    cursor.execute("""
        SELECT w.* FROM workspaces w
        JOIN workspace_members wm ON w.workspace_id = wm.workspace_id
        WHERE wm.user_id = ?
        ORDER BY w.created_at ASC LIMIT 1;
    """, (user_dict["user_id"],))
    ws_row = cursor.fetchone()
    conn.close()

    workspace_id = ws_row["workspace_id"] if ws_row else DEFAULT_WORKSPACE_ID
    merchant_name = ws_row["merchant_name"] if ws_row else "Default Workspace"
    onboarding_completed = bool(ws_row["onboarding_completed"]) if ws_row else True

    session = create_session(user_id=user_dict["user_id"], workspace_id=workspace_id, db_path=db_path)

    return {
        "user_id": user_dict["user_id"],
        "email": user_dict["email"],
        "full_name": user_dict["full_name"],
        "workspace_id": workspace_id,
        "merchant_name": merchant_name,
        "onboarding_completed": onboarding_completed,
        "session_token": session["session_token"],
        "expires_at": session["expires_at"],
        "user": {
            "id": user_dict["user_id"],
            "email": user_dict["email"],
            "full_name": user_dict["full_name"]
        },
        "workspace": {
            "id": workspace_id,
            "name": merchant_name,
            "environment": ws_row["environment"] if ws_row else "SANDBOX",
            "onboarding_completed": onboarding_completed
        }
    }


def create_session(user_id: str, workspace_id: str, db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """Generates a secure 30-day session token."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    session_token = f"sess_{secrets.token_hex(24)}"
    now_dt = datetime.utcnow()
    expires_dt = now_dt + timedelta(days=30)
    now_str = now_dt.isoformat() + "Z"
    expires_str = expires_dt.isoformat() + "Z"

    cursor.execute("""
        INSERT INTO sessions (session_token, user_id, workspace_id, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?);
    """, (session_token, user_id, workspace_id, expires_str, now_str))

    conn.commit()
    conn.close()

    return {
        "session_token": session_token,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "expires_at": expires_str
    }


def get_session(session_token: str, db_path: str = "data/recover_ai.db") -> Optional[Dict[str, Any]]:
    """Retrieves valid session details if token exists and has not expired."""
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.*, u.email, u.full_name, w.merchant_name, w.onboarding_completed, w.environment
        FROM sessions s
        JOIN users u ON s.user_id = u.user_id
        JOIN workspaces w ON s.workspace_id = w.workspace_id
        WHERE s.session_token = ?;
    """, (session_token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    sess = dict(row)
    now_str = datetime.utcnow().isoformat() + "Z"
    if sess["expires_at"] < now_str:
        return None

    return sess


def invalidate_session(session_token: str, db_path: str = "data/recover_ai.db") -> bool:
    """Deletes active session token."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE session_token = ?;", (session_token,))
    conn.commit()
    conn.close()
    return True


def create_api_key(
    workspace_id: str,
    name: str = "Production Secret Key",
    environment: str = "SANDBOX",
    db_path: str = "data/recover_ai.db"
) -> Dict[str, Any]:
    """
    Generates a new API key (`rai_live_...` or `rai_test_...`), stores its SHA-256 hash,
    and returns the raw key ONCE to the caller.
    """
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    key_id = f"key_{uuid4().hex[:8]}"
    prefix = "rai_test_" if environment.upper() == "SANDBOX" else "rai_live_"
    raw_secret = secrets.token_hex(20)
    raw_key = f"{prefix}{raw_secret}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_prefix_display = f"{prefix}{raw_secret[:4]}...{raw_secret[-4:]}"
    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("""
        INSERT INTO api_keys (key_id, workspace_id, name, key_prefix, key_hash, environment, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (key_id, workspace_id, name.strip(), key_prefix_display, key_hash, environment.upper(), now_str))

    conn.commit()
    conn.close()

    return {
        "key_id": key_id,
        "workspace_id": workspace_id,
        "name": name,
        "environment": environment.upper(),
        "key_prefix": key_prefix_display,
        "raw_key": raw_key,
        "raw_api_key": raw_key,
        "created_at": now_str
    }


def verify_api_key(raw_key: str, db_path: str = "data/recover_ai.db") -> Optional[str]:
    """
    Verifies raw API key against stored SHA-256 hashes and returns associated workspace_id.
    """
    if not raw_key or not raw_key.startswith(("rai_live_", "rai_test_")):
        return None

    ensure_tenancy_tables_and_columns_exist(db_path)
    key_hash = hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT workspace_id FROM api_keys
        WHERE key_hash = ? AND revoked_at IS NULL;
    """, (key_hash,))
    row = cursor.fetchone()
    conn.close()

    return row["workspace_id"] if row else None


def revoke_api_key(key_id: str, workspace_id: str, db_path: str = "data/recover_ai.db") -> bool:
    """Revokes an API key for a specific workspace."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("""
        UPDATE api_keys
        SET revoked_at = ?
        WHERE key_id = ? AND workspace_id = ?;
    """, (now_str, key_id, workspace_id))

    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def get_api_keys(workspace_id: str, db_path: str = "data/recover_ai.db") -> List[Dict[str, Any]]:
    """Lists all active and revoked API keys for a workspace (without exposing raw secret keys)."""
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT key_id, workspace_id, name, key_prefix, environment, created_at, revoked_at
        FROM api_keys
        WHERE workspace_id = ?
        ORDER BY created_at DESC;
    """, (workspace_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def seed_workspace_demo_data(workspace_id: str, db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """
    Generates a realistic sandbox recovery dataset (Payment Failure, Checkout Abandonment,
    Subscription Failure, Overdue Invoice) scoped strictly to the given workspace_id.
    """
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    categories = [
        {"cat": "PAYMENT FAILURE", "prefix": "pay_fail", "action": "RETRY", "amount_range": (2000, 15000)},
        {"cat": "CHECKOUT ABANDONMENT", "prefix": "cart_abnd", "action": "PAYMENT_LINK", "amount_range": (5000, 45000)},
        {"cat": "SUBSCRIPTION FAILURE", "prefix": "sub_fail", "action": "REMINDER", "amount_range": (1500, 12000)},
        {"cat": "OVERDUE INVOICE", "prefix": "inv_overdue", "action": "ESCALATE", "amount_range": (80000, 250000)}
    ]

    now = datetime.utcnow()
    created_count = 0
    total_value = 0.0

    for i in range(12):
        spec = categories[i % len(categories)]
        event_id = f"evt_demo_{spec['prefix']}_{uuid4().hex[:6]}"
        cust_id = f"cust_demo_{100 + i}"
        amount = round(secrets.randbelow(int(spec["amount_range"][1] - spec["amount_range"][0])) + spec["amount_range"][0] + secrets.randbelow(99) / 100.0, 2)
        prob = round(0.40 + (secrets.randbelow(55) / 100.0), 4)

        if amount > 100000.0 and i % 2 == 0:
            p_decision = "APPROVAL_REQUIRED"
            outcome = "PENDING_APPROVAL"
            reason = "Transaction amount > ₹1,00,000 INR requires human approval."
        elif i % 3 == 0:
            p_decision = "APPROVED: policy_v2_2026"
            outcome = "SUCCEEDED"
            reason = f"ML score ({prob}) > threshold. Deterministic policy approved {spec['action']}."
        else:
            p_decision = "APPROVED: policy_v2_2026"
            outcome = "PENDING"
            reason = f"Automated recovery scheduled via {spec['action']}."

        ts = (now - timedelta(hours=i * 2)).isoformat() + "Z"

        cursor.execute("""
            INSERT INTO revenue_events (
                event_id, customer_id, amount, event_type, failure_reason,
                archetype, recovery_probability, recommended_action, executed_action,
                policy_decision, outcome, reasoning_text, timestamp, workspace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            event_id, cust_id, amount, "payment.failed", "card_declined",
            spec["cat"], prob, spec["action"], spec["action"],
            p_decision, outcome, reason, ts, workspace_id
        ))

        created_count += 1
        total_value += amount

    conn.commit()
    conn.close()

    return {
        "workspace_id": workspace_id,
        "cases_created": created_count,
        "total_revenue_at_risk": round(total_value, 2)
    }
