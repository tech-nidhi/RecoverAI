"""
Webhook Event Processing and Recovery Engine Orchestration Service.
"""

import json
import sqlite3
import random
from datetime import datetime
from typing import Dict, Any, Optional

from schema.webhook_schema import NormalizedWebhookEvent
from schema.event_schema import RevenueEvent, CustomerHistorySummary
from policy.policy_engine import evaluate_policy
from policy.governance import evaluate_governance


def ensure_webhook_tables_exist(db_path: str = "data/recover_ai.db") -> None:
    """Ensures webhook_events table exists in SQLite database."""
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
            raw_payload TEXT
        );
    """)
    conn.commit()
    conn.close()


def persist_webhook_event(
    event: NormalizedWebhookEvent,
    raw_payload: Optional[Dict[str, Any]] = None,
    db_path: str = "data/recover_ai.db"
) -> None:
    """
    Persists normalized webhook event into SQLite webhook_events table.
    """
    ensure_webhook_tables_exist(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO webhook_events (
            event_id, source, source_event, event_type, payment_id, order_id,
            amount, currency, customer_reference, occurred_at, received_at,
            processing_status, error_message, raw_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        event.event_id, event.source, event.source_event, event.event_type,
        event.payment_id, event.order_id, event.amount, event.currency,
        event.customer_reference, event.occurred_at, event.received_at,
        event.processing_status, event.error_message,
        json.dumps(raw_payload) if raw_payload else None
    ))

    conn.commit()
    conn.close()


def update_webhook_status(
    event_id: str,
    status: str,
    error_message: Optional[str] = None,
    db_path: str = "data/recover_ai.db"
) -> None:
    """Updates processing status of a webhook event in SQLite."""
    conn = sqlite3.connect(db_path)
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
    event: NormalizedWebhookEvent,
    db_path: str = "data/recover_ai.db"
) -> Dict[str, Any]:
    """
    Processes an ingested webhook event through the RecoverAI pipeline:
    1. Evaluates event type relevance.
    2. For payment.failed: creates/updates revenue recovery case, scores risk, evaluates policy rules.
    3. For payment.captured/paid: updates case outcome to SUCCESS.
    4. Updates webhook_events processing status to PROCESSED / IGNORED.
    """
    ensure_webhook_tables_exist(db_path)

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

        # Heuristic ML Risk Scoring (simulate trained classifier inference)
        if amount >= 50000:
            recovery_prob = round(random.uniform(0.85, 0.98), 4)
            recommended_action = "PAYMENT_LINK"
        elif amount >= 15000:
            recovery_prob = round(random.uniform(0.65, 0.90), 4)
            recommended_action = "RETRY"
        else:
            recovery_prob = round(random.uniform(0.35, 0.80), 4)
            recommended_action = "REMINDER"

        # Create temporary RevenueEvent for Policy Engine check
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

        # Evaluate Policy Engine
        policy_res = evaluate_policy(temp_schema_event, recommended_action)
        
        # Evaluate Governance & Kill Switch Layer
        gov_decision = evaluate_governance({
            "event_id": case_id,
            "customer_id": cust_id,
            "amount": amount,
            "attempt_count": 1,
            "days_since_last_attempt": 0.1
        }, recommended_action, db_path=db_path)

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

        # Insert or Replace in revenue_events table (Live Queue & Audit Trail)
        cursor.execute("""
            INSERT OR REPLACE INTO revenue_events (
                event_id, event_type, timestamp, amount, customer_id, failure_reason,
                attempt_count, days_since_last_attempt, customer_history_summary,
                total_past_payments, past_successful_payments, past_recovery_rate,
                archetype, did_recover, recovery_probability, recommended_action,
                policy_decision, executed_action, outcome, revenue_recovered, reasoning_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            case_id, "payment_failure", event.occurred_at, amount, cust_id, "GATEWAY_TIMEOUT",
            1, 0.1, f"Live webhook customer {cust_id}",
            10, 9, 0.90,
            "transient_high_value", 0, recovery_prob, recommended_action,
            decision_str, final_action, outcome_str, 0.0, reasoning
        ))

        conn.commit()
        conn.close()

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
            "policy_approved": policy_res.approved
        }

    # 3. Process PAYMENT_CAPTURED / PAYMENT_LINK_PAID / ORDER_PAID -> Mark RECOVERED
    elif event.event_type in ["PAYMENT_CAPTURED", "PAYMENT_LINK_PAID", "ORDER_PAID"]:
        cursor.execute("""
            UPDATE revenue_events
            SET outcome = 'SUCCESS', revenue_recovered = amount, did_recover = 1
            WHERE customer_id = ? OR event_id LIKE ?;
        """, (event.customer_reference, f"%{event.payment_id or 'xyz'}%"))

        conn.commit()
        conn.close()

        update_webhook_status(event.event_id, "PROCESSED", db_path=db_path)

        return {
            "status": "PROCESSED",
            "event_type": event.event_type,
            "recovered_amount": event.amount
        }

    conn.close()
    update_webhook_status(event.event_id, "PROCESSED", db_path=db_path)
    return {"status": "PROCESSED", "event_id": event.event_id}
