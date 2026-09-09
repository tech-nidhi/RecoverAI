"""
Policy Governance Layer, Human Approval Workflow, and Global Kill Switch Engine (Multi-Tenant Aware).
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import uuid4

from schema.governance_schema import (
    GovernancePolicyConfig,
    PolicyDecision,
)
from auth.tenancy import ensure_tenancy_tables_and_columns_exist, DEFAULT_WORKSPACE_ID

DEFAULT_GOVERNANCE_CONFIG = GovernancePolicyConfig()


def ensure_governance_tables_exist(db_path: str = "data/recover_ai.db") -> None:
    """Ensures governance_config, approval_requests, and governance_audit_logs tables exist with tenancy columns."""
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS governance_config (
            key TEXT,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            workspace_id TEXT DEFAULT 'ws_default',
            PRIMARY KEY (workspace_id, key)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            amount REAL NOT NULL,
            action TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            decided_at TEXT,
            decided_by TEXT,
            rejection_reason TEXT,
            workspace_id TEXT DEFAULT 'ws_default'
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS governance_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            details TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            workspace_id TEXT DEFAULT 'ws_default'
        );
    """)

    conn.commit()
    conn.close()


def get_governance_config(
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> GovernancePolicyConfig:
    """Loads active governance policy config from SQLite database for a specific workspace."""
    ensure_governance_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    cursor.execute("SELECT key, value FROM governance_config WHERE workspace_id = ?;", (workspace_id,))
    rows = dict(cursor.fetchall())
    
    # Fallback to ws_default if target workspace has no config yet
    if not rows and workspace_id != DEFAULT_WORKSPACE_ID:
        cursor.execute("SELECT key, value FROM governance_config WHERE workspace_id = ?;", (DEFAULT_WORKSPACE_ID,))
        rows = dict(cursor.fetchall())

    conn.close()

    if not rows:
        return DEFAULT_GOVERNANCE_CONFIG

    try:
        return GovernancePolicyConfig(
            global_automation_active=json.loads(rows.get("global_automation_active", "true")),
            policy_version=rows.get("policy_version", "policy_v2_2026"),
            max_retries=int(rows.get("max_retries", "3")),
            retry_cooldown_hours=float(rows.get("retry_cooldown_hours", "24.0")),
            max_daily_auto_exposure=float(rows.get("max_daily_auto_exposure", "100000000.0")),
            max_customer_interventions=int(rows.get("max_customer_interventions", "3")),
            human_approval_threshold=float(rows.get("human_approval_threshold", "100000.0")),
            action_controls=json.loads(rows.get("action_controls", '{"RETRY":true,"PAYMENT_LINK":true,"REMINDER":true,"ESCALATE":true}'))
        )
    except Exception:
        return DEFAULT_GOVERNANCE_CONFIG


def update_governance_config(
    updates: Dict[str, Any],
    actor: str = "ADMIN",
    reason: Optional[str] = None,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> GovernancePolicyConfig:
    """Updates governance config in SQLite database and logs change to Audit Trail for a specific workspace."""
    ensure_governance_tables_exist(db_path)
    config = get_governance_config(db_path, workspace_id=workspace_id)
    config_dict = config.dict()
    config_dict.update(updates)
    new_config = GovernancePolicyConfig(**config_dict)

    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat() + "Z"

    for key, val in new_config.dict().items():
        val_str = json.dumps(val) if isinstance(val, (dict, list, bool)) else str(val)
        cursor.execute("""
            INSERT OR REPLACE INTO governance_config (key, value, updated_at, workspace_id)
            VALUES (?, ?, ?, ?);
        """, (key, val_str, now_str, workspace_id))

    # Log audit entry
    audit_detail = f"Config updated by {actor}: {updates}. Reason: {reason or 'N/A'}"
    cursor.execute("""
        INSERT INTO governance_audit_logs (event_type, actor, details, timestamp, workspace_id)
        VALUES (?, ?, ?, ?, ?);
    """, ("POLICY_CHANGED", actor, audit_detail, now_str, workspace_id))

    conn.commit()
    conn.close()

    return new_config


def record_governance_audit(
    event_type: str,
    actor: str,
    details: str,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> None:
    """Records an explicit governance event into SQLite governance_audit_logs."""
    ensure_governance_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("""
        INSERT INTO governance_audit_logs (event_type, actor, details, timestamp, workspace_id)
        VALUES (?, ?, ?, ?, ?);
    """, (event_type, actor, details, now_str, workspace_id))

    conn.commit()
    conn.close()


def get_todays_automated_exposure(
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> float:
    """Calculates today's total automated recovery exposure executed so far for a workspace."""
    ensure_governance_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0.0) FROM revenue_events
        WHERE (policy_decision = 'APPROVED: policy_v2_2026' OR policy_decision = 'AUTHORIZED: human_approved')
        AND timestamp LIKE ? AND workspace_id = ?;
    """, (f"{today_str}%", workspace_id))
    
    total = cursor.fetchone()[0]
    conn.close()
    return float(total)


def evaluate_governance(
    case_data: Dict[str, Any],
    recommended_action: str,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> PolicyDecision:
    """
    Authoritative backend governance evaluation pipeline.
    """
    config = get_governance_config(db_path, workspace_id=workspace_id)
    action = recommended_action.strip().upper()
    amount = float(case_data.get("amount", 0.0))
    customer_id = str(case_data.get("customer_id", "unknown"))
    attempt_count = int(case_data.get("attempt_count", 1))
    days_since_last = float(case_data.get("days_since_last_attempt", 1.0))
    case_id = str(case_data.get("event_id") or case_data.get("case_id") or f"case_{uuid4().hex[:6]}")

    # 1. Global Kill Switch Check
    if not config.global_automation_active:
        return PolicyDecision(
            decision="BLOCK",
            action=action,
            policy_version=config.policy_version,
            kill_switch_active=False,
            action_enabled=True,
            rejection_reason="GLOBAL_AUTOMATION_PAUSED"
        )

    # 2. Action Control Check
    if not config.action_controls.get(action, True):
        return PolicyDecision(
            decision="BLOCK",
            action=action,
            policy_version=config.policy_version,
            kill_switch_active=True,
            action_enabled=False,
            rejection_reason="ACTION_AUTOMATION_DISABLED"
        )

    # 3. Retry Limit Check
    if action == "RETRY" and attempt_count >= config.max_retries:
        return PolicyDecision(
            decision="BLOCK",
            action=action,
            policy_version=config.policy_version,
            kill_switch_active=True,
            retry_limit_satisfied=False,
            rejection_reason="MAX_RETRY_LIMIT_REACHED"
        )

    # 4. Cooldown Window Check
    cooldown_days = config.retry_cooldown_hours / 24.0
    if action == "RETRY" and days_since_last < cooldown_days:
        return PolicyDecision(
            decision="BLOCK",
            action=action,
            policy_version=config.policy_version,
            kill_switch_active=True,
            cooldown_satisfied=False,
            rejection_reason="COOLDOWN_ACTIVE"
        )

    # 5. Daily Automated Exposure Cap Check
    todays_exp = get_todays_automated_exposure(db_path=db_path, workspace_id=workspace_id)
    exposure_ok = (todays_exp + amount) <= config.max_daily_auto_exposure
    if not exposure_ok:
        return PolicyDecision(
            decision="BLOCK",
            action=action,
            policy_version=config.policy_version,
            kill_switch_active=True,
            exposure_limit_satisfied=False,
            rejection_reason="DAILY_EXPOSURE_LIMIT_EXCEEDED"
        )

    # 6. Human Approval Threshold Check (> ₹1,00,000 INR)
    if amount > config.human_approval_threshold:
        approval_id = create_approval_request(
            case_id=case_id,
            customer_id=customer_id,
            amount=amount,
            action=action,
            policy_version=config.policy_version,
            reason="Amount exceeds automatic execution threshold.",
            db_path=db_path,
            workspace_id=workspace_id
        )

        return PolicyDecision(
            decision="APPROVAL_REQUIRED",
            action=action,
            policy_version=config.policy_version,
            kill_switch_active=True,
            human_approval_required=True,
            approval_id=approval_id
        )

    # All checks passed cleanly -> ALLOW
    return PolicyDecision(
        decision="ALLOW",
        action=action,
        policy_version=config.policy_version,
        kill_switch_active=True,
        human_approval_required=False
    )


def create_approval_request(
    case_id: str,
    customer_id: str,
    amount: float,
    action: str,
    policy_version: str,
    reason: str,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> str:
    """Creates a human approval request in SQLite database with a 30-minute expiration window."""
    ensure_governance_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    approval_id = f"appr_{uuid4().hex[:10]}"
    now_dt = datetime.utcnow()
    created_at = now_dt.isoformat() + "Z"
    expires_at = (now_dt + timedelta(minutes=30)).isoformat() + "Z"

    cursor.execute("""
        INSERT OR REPLACE INTO approval_requests (
            approval_id, case_id, customer_id, amount, action, policy_version,
            status, created_at, expires_at, rejection_reason, workspace_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        approval_id, case_id, customer_id, amount, action, policy_version,
        "PENDING_APPROVAL", created_at, expires_at, reason, workspace_id
    ))

    # Log to Audit Trail
    cursor.execute("""
        INSERT INTO governance_audit_logs (event_type, actor, details, timestamp, workspace_id)
        VALUES (?, ?, ?, ?, ?);
    """, ("APPROVAL_REQUIRED", "SYSTEM", f"Approval required for case {case_id} (Amount: ₹{amount:,.2f}, Action: {action})", created_at, workspace_id))

    conn.commit()
    conn.close()

    return approval_id


def get_pending_approvals(
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> List[Dict[str, Any]]:
    """Returns active pending approval requests for a workspace and auto-expires old ones."""
    ensure_governance_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("""
        UPDATE approval_requests
        SET status = 'APPROVAL_EXPIRED'
        WHERE status = 'PENDING_APPROVAL' AND expires_at < ? AND workspace_id = ?;
    """, (now_str, workspace_id))
    conn.commit()

    cursor.execute("""
        SELECT * FROM approval_requests
        WHERE status = 'PENDING_APPROVAL' AND workspace_id = ?
        ORDER BY created_at DESC;
    """, (workspace_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def decide_approval_request(
    approval_id: str,
    decision: str,  # "APPROVE" or "REJECT"
    actor: str = "ADMIN",
    notes: Optional[str] = None,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> Dict[str, Any]:
    """Processes manual human approval or rejection decision."""
    ensure_governance_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("SELECT * FROM approval_requests WHERE approval_id = ? AND workspace_id = ?;", (approval_id, workspace_id))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError(f"Approval request '{approval_id}' not found.")

    req = dict(row)

    if req["status"] == "PENDING_APPROVAL" and req["expires_at"] < now_str:
        cursor.execute("UPDATE approval_requests SET status = 'APPROVAL_EXPIRED' WHERE approval_id = ?;", (approval_id,))
        conn.commit()
        conn.close()
        raise ValueError(f"Approval request '{approval_id}' has expired.")

    if req["status"] != "PENDING_APPROVAL":
        conn.close()
        raise ValueError(f"Approval request '{approval_id}' already has status '{req['status']}'.")

    new_status = "AUTHORIZED" if decision.upper() == "APPROVE" else "HUMAN_REJECTED"
    event_name = "HUMAN_APPROVED" if decision.upper() == "APPROVE" else "HUMAN_REJECTED"

    cursor.execute("""
        UPDATE approval_requests
        SET status = ?, decided_at = ?, decided_by = ?, rejection_reason = ?
        WHERE approval_id = ? AND workspace_id = ?;
    """, (new_status, now_str, actor, notes or decision.upper(), approval_id, workspace_id))

    audit_detail = f"Human decision by {actor} for case {req['case_id']} ({req['action']}, ₹{req['amount']:,.2f}): {new_status}"
    cursor.execute("""
        INSERT INTO governance_audit_logs (event_type, actor, details, timestamp, workspace_id)
        VALUES (?, ?, ?, ?, ?);
    """, (event_name, actor, audit_detail, now_str, workspace_id))

    if decision.upper() == "APPROVE":
        cursor.execute("""
            UPDATE revenue_events
            SET policy_decision = 'AUTHORIZED: human_approved', outcome = 'READY'
            WHERE event_id = ? AND workspace_id = ?;
        """, (req["case_id"], workspace_id))
    else:
        cursor.execute("""
            UPDATE revenue_events
            SET policy_decision = 'BLOCKED: human_rejected', outcome = 'NO_ACTION'
            WHERE event_id = ? AND workspace_id = ?;
        """, (req["case_id"], workspace_id))

    conn.commit()
    conn.close()

    return {
        "approval_id": approval_id,
        "case_id": req["case_id"],
        "decision": decision.upper(),
        "status": new_status,
        "actor": actor,
        "decided_at": now_str
    }
