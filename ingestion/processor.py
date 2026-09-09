"""
Webhook Event Processing and Recovery Engine Orchestration Service (Multi-Tenant Aware).
"""

import json
import sqlite3
import random
from datetime import datetime
from typing import Dict, Any, Optional

from schema.webhook_schema import NormalizedWebhookEvent
from schema.event_schema import RevenueEvent, CustomerHistorySummary
from policy.policy_engine import evaluate_policy
from policy.governance import evaluate_governance, record_governance_audit
from execution.idempotency import execute_action_idempotent, ensure_action_executions_table_exists
from auth.tenancy import ensure_tenancy_tables_and_columns_exist, DEFAULT_WORKSPACE_ID


def ensure_webhook_tables_exist(db_path: str = "data/recover_ai.db") -> None:
    """Ensures webhook_events table exists in SQLite database with workspace_id."""
    ensure_tenancy_tables_and_columns_exist(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            source TEXT,
            source_event TEXT,
            event_type TEXT,
            payment_id TEXT,
            order_id TEXT,
            amount REAL,
            currency TEXT,
            customer_reference TEXT,
            occurred_at TEXT,
            received_at TEXT,
            processing_status TEXT,
            processed_at TEXT,
            error_message TEXT,
            raw_payload TEXT,
            workspace_id TEXT DEFAULT 'ws_default',
            UNIQUE(source, event_id)
        );
    """)
    conn.commit()
    conn.close()


def persist_webhook_event(
    event: NormalizedWebhookEvent,
    raw_payload: Optional[Dict[str, Any]] = None,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> None:
    """
    Persists normalized webhook event into SQLite webhook_events table.
    """
    ensure_webhook_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO webhook_events (
                event_id, source, source_event, event_type, payment_id, order_id,
                amount, currency, customer_reference, occurred_at, received_at,
                processing_status, error_message, raw_payload, workspace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            event.event_id, event.source, event.source_event, event.event_type,
            event.payment_id, event.order_id, event.amount, event.currency,
            event.customer_reference, event.occurred_at, event.received_at,
            event.processing_status or "PROCESSING", event.error_message,
            json.dumps(raw_payload.dict() if hasattr(raw_payload, "dict") else raw_payload) if raw_payload else None, workspace_id
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


def update_webhook_status(
    event_id: str,
    status: str,
    error_message: Optional[str] = None,
    db_path: str = "data/recover_ai.db"
) -> None:
    """Updates processing status of a webhook event in SQLite."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    processed_at = datetime.utcnow().isoformat() + "Z"
    cursor.execute("""
        UPDATE webhook_events
        SET processing_status = ?, processed_at = ?, error_message = ?
        WHERE event_id = ?;
    """, (status, processed_at, error_message, event_id))
    conn.commit()
    conn.close()


def process_incoming_webhook_event(
    raw_payload: Dict[str, Any],
    signature_valid: bool = True,
    db_path: str = "data/recover_ai.db",
    workspace_id: str = DEFAULT_WORKSPACE_ID
) -> Dict[str, Any]:
    """
    Main orchestration entrypoint for processing Razorpay webhooks.
    """
    from ingestion.normalizer import normalize_razorpay_payload

    if not signature_valid:
        record_governance_audit(
            event_type="WEBHOOK_SIGNATURE_FAILED",
            actor="SYSTEM",
            details="Rejected Razorpay webhook due to invalid HMAC SHA256 signature.",
            db_path=db_path,
            workspace_id=workspace_id
        )
        return {
            "status": "REJECTED",
            "message": "Invalid webhook signature.",
            "event_id": (raw_payload.get("event") if isinstance(raw_payload, dict) else getattr(raw_payload, "event_id", "unknown")) or "unknown"
        }

    if isinstance(raw_payload, NormalizedWebhookEvent):
        event = raw_payload
    else:
        event = normalize_razorpay_payload(raw_payload)

    # Deduplication check
    ensure_webhook_tables_exist(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM webhook_events WHERE event_id = ? AND workspace_id = ?;", (event.event_id, workspace_id))
    existing = cursor.fetchone()

    if existing:
        ex_dict = dict(existing)
        status_val = ex_dict.get("processing_status")
        if status_val == "PROCESSED":
            conn.close()
            record_governance_audit(
                event_type="DUPLICATE_WEBHOOK_IGNORED",
                actor="SYSTEM",
                details=f"Duplicate webhook {event.event_id} ({event.source_event}) received. Already processed safely. Processing skipped.",
                db_path=db_path,
                workspace_id=workspace_id
            )
            return {
                "status": "DUPLICATE",
                "message": "Event already processed. Duplicate ignored safely.",
                "event_id": event.event_id
            }
        elif status_val == "PROCESSING":
            conn.close()
            record_governance_audit(
                event_type="CONCURRENT_WEBHOOK_BLOCKED",
                actor="SYSTEM",
                details=f"Concurrent webhook {event.event_id} ({event.source_event}) received while processing. Concurrent duplicate blocked.",
                db_path=db_path,
                workspace_id=workspace_id
            )
            return {
                "status": "ALREADY_PROCESSING",
                "message": "Event is currently processing.",
                "event_id": event.event_id
            }
    conn.close()

    # Persist event into webhook_events table in PROCESSING status
    persist_webhook_event(event, raw_payload=raw_payload, db_path=db_path, workspace_id=workspace_id)

    # 1. Handle unsupported events gracefully
    if event.event_type == "UNSUPPORTED":
        msg = f"RecoverAI currently ignores unsupported source event '{event.source_event}'"
        update_webhook_status(event.event_id, "IGNORED", error_message=msg, db_path=db_path)
        return {"status": "IGNORED", "message": msg, "event_id": event.event_id}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 2. Process PAYMENT_FAILED event -> Create & Score Recovery Case
    if event.event_type == "PAYMENT_FAILED":
        case_id = f"evt_rzp_{event.payment_id or event.event_id[-8:]}"
        cust_id = event.customer_reference
        amount = event.amount

        if amount >= 50000:
            recovery_prob = round(random.uniform(0.85, 0.98), 4)
            recommended_action = "PAYMENT_LINK"
        elif amount >= 15000:
            recovery_prob = round(random.uniform(0.65, 0.90), 4)
            recommended_action = "RETRY"
        else:
            recovery_prob = round(random.uniform(0.35, 0.80), 4)
            recommended_action = "REMINDER"

        temp_schema_event = RevenueEvent(
            event_id=case_id,
            event_type="payment_failure",
            timestamp=datetime.utcnow(),
            amount=amount,
            customer_id=cust_id,
            failure_reason="GATEWAY_TIMEOUT",
            attempt_count=1,
            days_since_last_attempt=0.1,
            customer_history_summary=CustomerHistorySummary(
                total_past_payments=10,
                past_successful_payments=9,
                past_recovery_rate=0.90
            ),
            archetype="transient_high_value",
            did_recover=False,
            recovery_probability=recovery_prob
        )

        policy_res = evaluate_policy(temp_schema_event, recommended_action)
        
        gov_decision = evaluate_governance({
            "event_id": case_id,
            "customer_id": cust_id,
            "amount": amount,
            "attempt_count": 1,
            "days_since_last_attempt": 0.1
        }, recommended_action, db_path=db_path, workspace_id=workspace_id)

        if gov_decision.decision == "ALLOW" and policy_res.approved:
            final_action = policy_res.final_action
            decision_str = f"APPROVED: {gov_decision.policy_version}"
            outcome_str = "READY"
        elif gov_decision.decision == "APPROVAL_REQUIRED":
            final_action = recommended_action
            decision_str = f"APPROVAL_REQUIRED: amount_above_threshold ({gov_decision.approval_id})"
            outcome_str = "PENDING_APPROVAL"
        else:
            final_action = "STOP"
            reason_code = gov_decision.rejection_reason or policy_res.blocking_rule or "GOVERNANCE_BLOCKED"
            decision_str = f"BLOCKED: {reason_code}"
            outcome_str = "NO_ACTION"

        reasoning = f"Webhook payment.failed ingested for {cust_id}. Amount ₹{amount:,.2f} INR scored with {recovery_prob*100:.1f}% recovery probability. Recommended: {recommended_action}, Final Action: {final_action} ({decision_str})."

        cursor.execute("""
            INSERT OR REPLACE INTO revenue_events (
                event_id, event_type, timestamp, amount, customer_id, failure_reason,
                attempt_count, days_since_last_attempt, customer_history_summary,
                total_past_payments, past_successful_payments, past_recovery_rate,
                archetype, did_recover, recovery_probability, recommended_action,
                policy_decision, executed_action, outcome, revenue_recovered, reasoning_text, workspace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            case_id, "payment_failure", event.occurred_at, amount, cust_id, "GATEWAY_TIMEOUT",
            1, 0.1, f"Live webhook customer {cust_id}",
            10, 9, 0.90,
            "transient_high_value", 0, recovery_prob, recommended_action,
            decision_str, final_action, outcome_str, 0.0, reasoning, workspace_id
        ))

        conn.commit()
        conn.close()

        idempotency_record = None
        if gov_decision.decision == "ALLOW" and policy_res.approved:
            idempotency_record = execute_action_idempotent(
                case_id=case_id,
                action_type=final_action,
                attempt_number=1,
                amount=amount,
                customer_id=cust_id,
                db_path=db_path,
                workspace_id=workspace_id
            )

        update_webhook_status(event.event_id, "PROCESSED", db_path=db_path)

        return {
            "status": "PROCESSED",
            "event_type": "PAYMENT_FAILED",
            "case_id": case_id,
            "amount": amount,
            "recovery_probability": recovery_prob,
            "recommended_action": recommended_action,
            "final_action": final_action,
            "governance_decision": gov_decision.decision,
            "policy_approved": policy_res.approved,
            "idempotency_key": idempotency_record.idempotency_key if idempotency_record else f"rc_{case_id}_{final_action}_1"
        }

    # 3. Process PAYMENT_CAPTURED / PAYMENT_LINK_PAID / ORDER_PAID -> Mark RECOVERED
    elif event.event_type in ["PAYMENT_CAPTURED", "PAYMENT_LINK_PAID", "ORDER_PAID"]:
        pay_id = event.payment_id or event.event_id[-8:]
        target_case_id = f"evt_rzp_{pay_id}"

        cursor.execute("""
            UPDATE revenue_events
            SET did_recover = 1, outcome = 'RECOVERED', revenue_recovered = amount
            WHERE (event_id = ? OR customer_id = ?) AND workspace_id = ?;
        """, (target_case_id, event.customer_reference, workspace_id))

        conn.commit()
        conn.close()

        update_webhook_status(event.event_id, "PROCESSED", db_path=db_path)

        record_governance_audit(
            event_type="PAYMENT_RECOVERED",
            actor="SYSTEM",
            details=f"Payment {pay_id} marked RECOVERED for customer {event.customer_reference} ({event.amount} INR).",
            db_path=db_path,
            workspace_id=workspace_id
        )

        return {
            "status": "PROCESSED",
            "event_type": event.event_type,
            "payment_id": pay_id,
            "recovered_amount": event.amount
        }

    else:
        update_webhook_status(event.event_id, "PROCESSED", db_path=db_path)
        return {"status": "PROCESSED", "event_type": event.event_type}
