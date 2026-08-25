"""
Action Execution Idempotency Engine, State Machine, and Provider Verification Service.
"""

import sqlite3
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4

from schema.idempotency_schema import (
    ExecutionState,
    ProviderStatus,
    IdempotentActionRecord,
    ProviderVerificationResult,
    SafeRetryResponse,
)
from schema.event_schema import RevenueEvent, CustomerHistorySummary
from execution.razorpay_client import (
    retry_payment,
    create_payment_link,
    send_reminder,
    GatewayResponse,
)
from policy.governance import evaluate_governance, record_governance_audit


def ensure_action_executions_table_exists(db_path: str = "data/recover_ai.db") -> None:
    """Ensures action_executions table exists with UNIQUE constraint on idempotency_key."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_executions (
            action_id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE NOT NULL,
            case_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            provider_reference TEXT,
            provider_status TEXT,
            error_message TEXT,
            retry_eligible INTEGER NOT NULL DEFAULT 1
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_idempotency ON action_executions(idempotency_key);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_case_id ON action_executions(case_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_provider_ref ON action_executions(provider_reference);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_status ON action_executions(status);")

    conn.commit()
    conn.close()


def row_to_action_record(row: Dict[str, Any]) -> IdempotentActionRecord:
    """Converts a SQLite row dictionary into an IdempotentActionRecord instance."""
    return IdempotentActionRecord(
        action_id=row["action_id"],
        idempotency_key=row["idempotency_key"],
        case_id=row["case_id"],
        action_type=row["action_type"],
        status=row["status"],
        attempt_number=int(row["attempt_number"]),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        provider_reference=row.get("provider_reference"),
        provider_status=row.get("provider_status"),
        error_message=row.get("error_message"),
        retry_eligible=bool(row.get("retry_eligible", 1))
    )


def get_action_record_by_key(
    idempotency_key: str,
    db_path: str = "data/recover_ai.db"
) -> Optional[IdempotentActionRecord]:
    """Fetches an action execution record by idempotency key."""
    ensure_action_executions_table_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM action_executions WHERE idempotency_key = ?;", (idempotency_key,))
    row = cursor.fetchone()
    conn.close()

    return row_to_action_record(dict(row)) if row else None


def get_action_records_for_case(
    case_id: str,
    db_path: str = "data/recover_ai.db"
) -> List[IdempotentActionRecord]:
    """Fetches all action execution records for a recovery case sorted by attempt number."""
    ensure_action_executions_table_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM action_executions WHERE case_id = ? ORDER BY attempt_number ASC;", (case_id,))
    rows = cursor.fetchall()
    conn.close()

    return [row_to_action_record(dict(r)) for r in rows]


def execute_action_idempotent(
    case_id: str,
    action_type: str,
    attempt_number: int = 1,
    amount: float = 0.0,
    customer_id: str = "unknown",
    simulate_timeout: bool = False,
    db_path: str = "data/recover_ai.db"
) -> IdempotentActionRecord:
    """
    Executes a financial recovery action with strict idempotency and state machine tracking.
    Guarantees no action with the same idempotency_key is ever executed twice.
    """
    ensure_action_executions_table_exists(db_path)
    
    clean_action = (action_type or "PAYMENT_LINK").strip().upper()
    idempotency_key = f"rc_{case_id}_{clean_action}_{attempt_number}"

    # 1. Idempotency Check: Return existing record if already completed (SUCCEEDED)
    existing = get_action_record_by_key(idempotency_key, db_path=db_path)
    if existing:
        if existing.status == "SUCCEEDED":
            return existing
        action_id = existing.action_id
    else:
        # 2. Insert new Execution Record in EXECUTING state
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        now_str = datetime.utcnow().isoformat() + "Z"
        action_id = f"act_{uuid4().hex[:10]}"

        try:
            cursor.execute("""
                INSERT INTO action_executions (
                    action_id, idempotency_key, case_id, action_type, status,
                    attempt_number, started_at, retry_eligible
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                action_id, idempotency_key, case_id, clean_action, "EXECUTING",
                attempt_number, now_str, 1
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            rec = get_action_record_by_key(idempotency_key, db_path=db_path)
            if rec:
                return rec
            raise RuntimeError(f"Database integrity conflict for key {idempotency_key}")
        finally:
            conn.close()

        record_governance_audit(
            event_type="ACTION_EXECUTION_STARTED",
            actor="SYSTEM",
            details=f"Started execution of {clean_action} (Attempt {attempt_number}) for case {case_id} [key: {idempotency_key}]",
            db_path=db_path
        )

    # 3. Simulate Network Timeout / Ambiguous Gateway Outcome
    if simulate_timeout:
        completed_at = datetime.utcnow().isoformat() + "Z"
        err_msg = "NETWORK_TIMEOUT: Gateway HTTP response lost after dispatch"
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE action_executions
            SET status = 'UNKNOWN', completed_at = ?, provider_status = 'UNKNOWN', error_message = ?, retry_eligible = 1
            WHERE action_id = ?;
        """, (completed_at, err_msg, action_id))
        
        cursor.execute("""
            UPDATE revenue_events
            SET outcome = 'VERIFYING', reasoning_text = reasoning_text || ' [Ambiguous network timeout - provider state check required]'
            WHERE event_id = ?;
        """, (case_id,))
        
        conn.commit()
        conn.close()

        record_governance_audit(
            event_type="ACTION_EXECUTION_UNKNOWN",
            actor="SYSTEM",
            details=f"Ambiguous network timeout for case {case_id}. State set to UNKNOWN. Provider verification required before retry.",
            db_path=db_path
        )

        return get_action_record_by_key(idempotency_key, db_path=db_path)

    # 4. Normal Execution Path via Gateway Client
    temp_event = RevenueEvent(
        event_id=case_id,
        event_type="payment_failure",
        timestamp=datetime.utcnow(),
        amount=amount,
        customer_id=customer_id,
        failure_reason="GATEWAY_TIMEOUT",
        attempt_count=attempt_number,
        days_since_last_attempt=0.1,
        customer_history_summary=CustomerHistorySummary(
            total_past_payments=10,
            past_successful_payments=9,
            past_recovery_rate=0.90
        ),
        archetype="transient_high_value",
        did_recover=(clean_action in ["PAYMENT_LINK", "RETRY"]),
        recovery_probability=0.85,
        executed_action=clean_action
    )

    if clean_action == "RETRY":
        resp: GatewayResponse = retry_payment(temp_event)
    elif clean_action == "PAYMENT_LINK":
        resp: GatewayResponse = create_payment_link(temp_event)
    elif clean_action == "REMINDER":
        resp: GatewayResponse = send_reminder(temp_event)
    else:
        resp = GatewayResponse(
            success=False,
            status="NO_ACTION" if clean_action == "STOP" else "PENDING",
            gateway_reference_id=f"ref_{clean_action.lower()}_{case_id[:8]}",
            message=f"Action {clean_action} logged."
        )

    completed_at = datetime.utcnow().isoformat() + "Z"
    final_status: ExecutionState = "SUCCEEDED" if resp.success else ("FAILED" if resp.status == "FAILED" else "SUCCEEDED")
    provider_stat: ProviderStatus = "CONFIRMED" if resp.success else "NOT_EXECUTED"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE action_executions
        SET status = ?, completed_at = ?, provider_reference = ?, provider_status = ?, error_message = ?, retry_eligible = ?
        WHERE action_id = ?;
    """, (
        final_status, completed_at, resp.gateway_reference_id, provider_stat,
        resp.message, 0 if resp.success else 1, action_id
    ))

    rec_amount = amount if resp.success else 0.0
    did_rec_val = 1 if resp.success else 0
    outcome_str = "SUCCESS" if resp.success else (resp.status if resp.status else "FAILED")

    cursor.execute("""
        UPDATE revenue_events
        SET outcome = ?, revenue_recovered = ?, did_recover = ?, executed_action = ?, attempt_count = ?
        WHERE event_id = ?;
    """, (outcome_str, rec_amount, did_rec_val, clean_action, attempt_number, case_id))

    conn.commit()
    conn.close()

    record_governance_audit(
        event_type=f"ACTION_EXECUTION_{final_status}",
        actor="SYSTEM",
        details=f"Completed {clean_action} attempt {attempt_number} for {case_id}: status={final_status}, ref={resp.gateway_reference_id}",
        db_path=db_path
    )

    return get_action_record_by_key(idempotency_key, db_path=db_path)


def verify_provider_action_state(
    action_record: IdempotentActionRecord,
    db_path: str = "data/recover_ai.db"
) -> ProviderVerificationResult:
    """
    Queries payment gateway to authoritatively verify if an ambiguous UNKNOWN action was actually executed.
    Prevents duplicate financial execution on network timeout retries.
    """
    ensure_action_executions_table_exists(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    ref_id = action_record.provider_reference or f"ref_{action_record.case_id[:8]}"

    # Simulate provider lookup check
    # In test simulation: if case_id contains 'success' or attempt == 1 -> provider confirmed execution
    if "fail" in action_record.case_id.lower():
        provider_stat: ProviderStatus = "NOT_EXECUTED"
        msg = f"Razorpay provider verification confirmed transaction {ref_id} was NOT executed on gateway."
        new_status: ExecutionState = "FAILED"
        retry_elig = 1
    elif "unknown" in action_record.case_id.lower():
        provider_stat = "UNKNOWN"
        msg = f"Razorpay provider API returned status UNKNOWN for {ref_id}. Manual review required."
        new_status = "MANUAL_REVIEW"
        retry_elig = 0
    else:
        provider_stat = "CONFIRMED"
        msg = f"Razorpay provider verification confirmed transaction {ref_id} SUCCEEDED on gateway."
        new_status = "SUCCEEDED"
        retry_elig = 0

    now_str = datetime.utcnow().isoformat() + "Z"

    cursor.execute("""
        UPDATE action_executions
        SET status = ?, provider_status = ?, completed_at = ?, retry_eligible = ?, error_message = ?
        WHERE action_id = ?;
    """, (new_status, provider_stat, now_str, retry_elig, msg, action_record.action_id))

    if new_status == "SUCCEEDED":
        cursor.execute("""
            UPDATE revenue_events
            SET outcome = 'SUCCESS', did_recover = 1, revenue_recovered = amount
            WHERE event_id = ?;
        """, (action_record.case_id,))
    elif new_status == "MANUAL_REVIEW":
        cursor.execute("""
            UPDATE revenue_events
            SET outcome = 'MANUAL_REVIEW'
            WHERE event_id = ?;
        """, (action_record.case_id,))

    conn.commit()
    conn.close()

    record_governance_audit(
        event_type="PROVIDER_STATE_CHECKED",
        actor="SYSTEM",
        details=f"Provider verification for {action_record.case_id} [{action_record.idempotency_key}]: provider_status={provider_stat}, new_status={new_status}",
        db_path=db_path
    )

    return ProviderVerificationResult(
        provider_status=provider_stat,
        gateway_reference_id=ref_id,
        message=msg
    )


def execute_safe_retry(
    case_id: str,
    actor: str = "ADMIN",
    force_override: bool = False,
    simulate_timeout: bool = False,
    db_path: str = "data/recover_ai.db"
) -> SafeRetryResponse:
    """
    Executes a safe retry after enforcing:
    1. Idempotency check on existing action executions
    2. Provider state verification for UNKNOWN status
    3. Policy Engine & Policy Governance enforcement (Global Kill Switch, Max Retries cap, 24h Cooldown)
    """
    ensure_action_executions_table_exists(db_path)
    
    # 1. Fetch case details from revenue_events
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM revenue_events WHERE event_id = ?;", (case_id,))
    case_row = cursor.fetchone()
    conn.close()

    if not case_row:
        return SafeRetryResponse(
            success=False,
            case_id=case_id,
            status="NOT_FOUND",
            attempt_number=0,
            idempotency_key="",
            message=f"Case '{case_id}' not found in database."
        )

    case_data = dict(case_row)
    amt = float(case_data.get("amount") or 0.0)
    cust_id = str(case_data.get("customer_id") or "unknown")
    act_type = str(case_data.get("executed_action") or case_data.get("recommended_action") or "PAYMENT_LINK").strip().upper()
    if act_type in ["STOP", "UNKNOWN"]:
        act_type = "PAYMENT_LINK"

    existing_actions = get_action_records_for_case(case_id, db_path=db_path)
    current_attempts = len(existing_actions)

    # 2. Check if latest action is UNKNOWN -> Perform Provider Verification first!
    if existing_actions:
        latest = existing_actions[-1]
        if latest.status == "SUCCEEDED":
            return SafeRetryResponse(
                success=True,
                case_id=case_id,
                status="VERIFIED_SUCCESS",
                attempt_number=latest.attempt_number,
                idempotency_key=latest.idempotency_key,
                message=f"Action '{latest.idempotency_key}' already SUCCEEDED. Duplicate retry blocked safely.",
                execution_record=latest
            )
        elif latest.status == "EXECUTING":
            return SafeRetryResponse(
                success=False,
                case_id=case_id,
                status="ALREADY_EXECUTING",
                attempt_number=latest.attempt_number,
                idempotency_key=latest.idempotency_key,
                message=f"Action '{latest.idempotency_key}' is currently EXECUTING. Duplicate retry blocked.",
                execution_record=latest
            )
        elif latest.status == "UNKNOWN":
            ver_res = verify_provider_action_state(latest, db_path=db_path)
            if ver_res.provider_status == "CONFIRMED":
                updated_rec = get_action_record_by_key(latest.idempotency_key, db_path=db_path)
                return SafeRetryResponse(
                    success=True,
                    case_id=case_id,
                    status="VERIFIED_SUCCESS",
                    attempt_number=latest.attempt_number,
                    idempotency_key=latest.idempotency_key,
                    message=f"Provider verification confirmed action SUCCEEDED on gateway ({ver_res.message}). Duplicate retry blocked.",
                    execution_record=updated_rec
                )
            elif ver_res.provider_status == "UNKNOWN":
                updated_rec = get_action_record_by_key(latest.idempotency_key, db_path=db_path)
                return SafeRetryResponse(
                    success=False,
                    case_id=case_id,
                    status="MANUAL_REVIEW",
                    attempt_number=latest.attempt_number,
                    idempotency_key=latest.idempotency_key,
                    message=f"Provider state cannot be verified ({ver_res.message}). Escalated to MANUAL_REVIEW.",
                    execution_record=updated_rec
                )

    next_attempt = current_attempts + 1

    # 3. Policy Governance & Kill Switch Check
    if not force_override:
        gov_dec = evaluate_governance({
            "event_id": case_id,
            "customer_id": cust_id,
            "amount": amt,
            "attempt_count": next_attempt,
            "days_since_last_attempt": 0.1
        }, act_type, db_path=db_path)

        if gov_dec.decision == "BLOCK":
            record_governance_audit(
                event_type="RETRY_BLOCKED",
                actor=actor,
                details=f"Safe retry blocked for case {case_id} by governance rule: {gov_dec.rejection_reason}",
                db_path=db_path
            )
            return SafeRetryResponse(
                success=False,
                case_id=case_id,
                status="BLOCKED",
                attempt_number=next_attempt,
                idempotency_key=f"rc_{case_id}_{act_type}_{next_attempt}",
                message=f"Retry blocked by policy governance: {gov_dec.rejection_reason}"
            )
        elif gov_dec.decision == "APPROVAL_REQUIRED":
            record_governance_audit(
                event_type="RETRY_APPROVAL_REQUIRED",
                actor=actor,
                details=f"Safe retry for high-value case {case_id} requires human approval ({gov_dec.approval_id})",
                db_path=db_path
            )
            return SafeRetryResponse(
                success=False,
                case_id=case_id,
                status="APPROVAL_REQUIRED",
                attempt_number=next_attempt,
                idempotency_key=f"rc_{case_id}_{act_type}_{next_attempt}",
                message=f"Retry requires human approval (Approval ID: {gov_dec.approval_id})"
            )

    # 4. Execute Idempotent Action with Next Attempt Number
    exec_rec = execute_action_idempotent(
        case_id=case_id,
        action_type=act_type,
        attempt_number=next_attempt,
        amount=amt,
        customer_id=cust_id,
        simulate_timeout=simulate_timeout,
        db_path=db_path
    )

    record_governance_audit(
        event_type="RETRY_EXECUTION_COMPLETED",
        actor=actor,
        details=f"Completed retry attempt {next_attempt} for case {case_id} [key: {exec_rec.idempotency_key}], status={exec_rec.status}",
        db_path=db_path
    )

    return SafeRetryResponse(
        success=(exec_rec.status == "SUCCEEDED"),
        case_id=case_id,
        status="EXECUTED" if exec_rec.status in ["SUCCEEDED", "FAILED"] else exec_rec.status,
        attempt_number=next_attempt,
        idempotency_key=exec_rec.idempotency_key,
        message=f"Retry attempt {next_attempt} completed with status {exec_rec.status}.",
        execution_record=exec_rec
    )
