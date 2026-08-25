"""
Structured Backend Operational Tools for RecoverAI AI Copilot.

Provides deterministic, read-only tools and safe simulation tools for querying RecoverAI
metrics, cases, policy decisions, governance status, transaction traces, and intervention performance.
Ensures zero arbitrary SQL generation by LLM.
"""

import sqlite3
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from analytics.attribution import compute_recovery_impact_metrics, get_transaction_attribution_trace
from analytics.experiments import get_all_experiments
from policy.governance import get_governance_config, get_pending_approvals, ensure_governance_tables_exist
from execution.idempotency import ensure_action_executions_table_exists


def _get_db_connection(db_path: str = "data/recover_ai.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_recovery_metrics(db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """
    Returns top-level recovery performance metrics: total revenue at risk, recovered revenue,
    overall recovery rate, organic baseline rate, estimated incremental lift, and net ROI.
    """
    impact = compute_recovery_impact_metrics(db_path=db_path)
    m = impact["metrics"]
    return {
        "tool_name": "get_recovery_metrics",
        "data": m,
        "source": {
            "type": "recovery_intelligence",
            "name": "Recovery Impact Engine",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    }


def get_recovery_cases(
    db_path: str = "data/recover_ai.db",
    category: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Returns filtered active recovery cases from revenue_events database table.
    """
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM revenue_events WHERE 1=1"
    params = []

    if category:
        query += " AND (event_type LIKE ? OR archetype LIKE ?)"
        params.extend([f"%{category}%", f"%{category}%"])
    if action:
        query += " AND (executed_action = ? OR recommended_action = ?)"
        params.extend([action.upper(), action.upper()])
    if status:
        query += " AND outcome = ?"
        params.append(status.upper())

    query += " ORDER BY rowid DESC LIMIT ?;"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "tool_name": "get_recovery_cases",
        "count": len(rows),
        "cases": rows,
        "filters": {"category": category, "action": action, "status": status, "limit": limit},
        "source": {"type": "revenue_events_db", "name": "Recovery Cases Queue"}
    }


def get_case_details(db_path: str = "data/recover_ai.db", case_id: str = "") -> Dict[str, Any]:
    """
    Returns complete details, ML probability, policy decisions, and reasoning text for a specific case_id.
    """
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM revenue_events WHERE event_id = ? OR event_id LIKE ? LIMIT 1;", (case_id, f"%{case_id}%"))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "tool_name": "get_case_details",
            "found": False,
            "case_id": case_id,
            "message": f"Case '{case_id}' was not found in RecoverAI database records."
        }

    case_data = dict(row)
    return {
        "tool_name": "get_case_details",
        "found": True,
        "case_id": case_data["event_id"],
        "data": case_data,
        "source": {"type": "revenue_events_db", "case_id": case_data["event_id"], "name": f"Case Record {case_data['event_id']}"}
    }


def get_transaction_trace(db_path: str = "data/recover_ai.db", transaction_id: str = "") -> Dict[str, Any]:
    """
    Returns transaction-level incremental attribution and execution trace.
    """
    try:
        trace = get_transaction_attribution_trace(transaction_id, db_path=db_path)
        data_dict = trace.model_dump() if hasattr(trace, "model_dump") else trace.dict()
        return {
            "tool_name": "get_transaction_trace",
            "found": True,
            "transaction_id": transaction_id,
            "data": data_dict,
            "source": {"type": "audit_trail", "id": transaction_id, "name": f"Audit Trace · {transaction_id}"}
        }
    except ValueError as e:
        return {
            "tool_name": "get_transaction_trace",
            "found": False,
            "transaction_id": transaction_id,
            "message": str(e)
        }


def get_audit_events(
    db_path: str = "data/recover_ai.db",
    event_type: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Returns recent governance and operational audit logs.
    """
    ensure_governance_tables_exist(db_path)
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM governance_audit_logs WHERE 1=1"
    params = []
    if event_type:
        query += " AND event_type LIKE ?"
        params.append(f"%{event_type}%")

    query += " ORDER BY id DESC LIMIT ?;"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "tool_name": "get_audit_events",
        "count": len(rows),
        "events": rows,
        "source": {"type": "governance_audit_logs", "name": "Governance Audit Trail"}
    }


def get_policy_decisions(
    db_path: str = "data/recover_ai.db",
    rule: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Returns policy decisions and blocked case logs.
    """
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT event_id, customer_id, amount, recommended_action, executed_action, policy_decision, outcome FROM revenue_events WHERE policy_decision IS NOT NULL"
    params = []
    if rule:
        query += " AND policy_decision LIKE ?"
        params.append(f"%{rule}%")

    query += " ORDER BY rowid DESC LIMIT ?;"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "tool_name": "get_policy_decisions",
        "count": len(rows),
        "decisions": rows,
        "source": {"type": "policy_engine", "name": "Policy Engine Decision Trace"}
    }


def get_governance_status(db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """
    Returns active Global Automation Kill Switch state, action controls, max retries, cooldown, and pending approvals.
    """
    ensure_governance_tables_exist(db_path)
    cfg = get_governance_config(db_path)
    cfg_dict = cfg.model_dump() if hasattr(cfg, "model_dump") else cfg.dict()
    approvals = get_pending_approvals(db_path)

    return {
        "tool_name": "get_governance_status",
        "data": {
            "global_automation_active": cfg_dict.get("global_automation_active", True),
            "action_controls": cfg_dict.get("action_controls", {}),
            "max_retry_attempts": cfg_dict.get("max_retry_attempts", 3),
            "retry_cooldown_hours": cfg_dict.get("retry_cooldown_hours", 24),
            "human_approval_threshold_inr": cfg_dict.get("human_approval_threshold_inr", 100000.0),
            "daily_exposure_limit_inr": cfg_dict.get("daily_exposure_limit_inr", 1000000.0),
            "pending_approvals_count": len(approvals)
        },
        "source": {"type": "policy_governance", "name": "Governance & Control Plane"}
    }


def get_intervention_performance(db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """
    Returns recovery rate, baseline, incremental lift, and sample size for each recovery intervention.
    """
    impact = compute_recovery_impact_metrics(db_path=db_path)
    return {
        "tool_name": "get_intervention_performance",
        "interventions": impact["interventions"],
        "source": {"type": "intervention_analytics", "name": "Intervention Attribution Analytics"}
    }


def get_recovery_attribution(db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """
    Returns incremental recovery attribution metrics, organic baseline breakdown, and execution costs.
    """
    impact = compute_recovery_impact_metrics(db_path=db_path)
    return {
        "tool_name": "get_recovery_attribution",
        "attribution": impact["metrics"],
        "event_types": impact["event_types"],
        "source": {"type": "attribution_service", "name": "Incremental ROI & Attribution Model"}
    }


def get_experiment_results(db_path: str = "data/recover_ai.db") -> Dict[str, Any]:
    """
    Returns active A/B strategy experiments and control vs treatment lift.
    """
    experiments = get_all_experiments(db_path)
    return {
        "tool_name": "get_experiment_results",
        "count": len(experiments),
        "experiments": experiments,
        "source": {"type": "strategy_experiments", "name": "Strategy Experiments Framework"}
    }


def get_execution_failures(db_path: str = "data/recover_ai.db", limit: int = 10) -> Dict[str, Any]:
    """
    Returns failed recovery executions and ambiguous network timeout actions from action_executions table.
    """
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    # Check if action_executions table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='action_executions';")
    if not cursor.fetchone():
        conn.close()
        return {"tool_name": "get_execution_failures", "count": 0, "failures": []}

    cursor.execute("""
        SELECT * FROM action_executions
        WHERE status IN ('FAILED', 'UNKNOWN', 'MANUAL_REVIEW')
        ORDER BY started_at DESC LIMIT ?;
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "tool_name": "get_execution_failures",
        "count": len(rows),
        "failures": rows,
        "source": {"type": "action_executions", "name": "Execution State Machine Log"}
    }


def get_top_revenue_at_risk(db_path: str = "data/recover_ai.db", limit: int = 5) -> Dict[str, Any]:
    """
    Returns top active recovery cases sorted by amount at risk and expected recoverable value.
    """
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT event_id, customer_id, amount, recovery_probability, recommended_action, executed_action, outcome, reasoning_text
        FROM revenue_events
        WHERE outcome NOT IN ('SUCCESS', 'CLOSED')
        ORDER BY (amount * COALESCE(recovery_probability, 0.8)) DESC LIMIT ?;
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]

    if not rows:
        cursor.execute("""
            SELECT event_id, customer_id, amount, recovery_probability, recommended_action, executed_action, outcome, reasoning_text
            FROM revenue_events
            ORDER BY amount DESC LIMIT ?;
        """, (limit,))
        rows = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "tool_name": "get_top_revenue_at_risk",
        "count": len(rows),
        "cases": rows,
        "source": {"type": "revenue_events_db", "name": "Revenue at Risk Pipeline"}
    }


def simulate_policy_change(
    db_path: str = "data/recover_ai.db",
    proposed_max_retries: int = 3,
    proposed_cooldown_hours: int = 24
) -> Dict[str, Any]:
    """
    Simulates proposed policy changes (e.g. max retries, cooldown) without modifying production policy.
    """
    conn = _get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), SUM(amount) FROM revenue_events WHERE outcome != 'SUCCESS';")
    row = cursor.fetchone()
    conn.close()

    total_unrecovered = row[0] or 100
    unrecovered_amt = row[1] or 500000.0

    # Calculate projected simulation lift
    current_max = 2
    retry_delta = max(0, proposed_max_retries - current_max)
    projected_lift_pct = round(retry_delta * 6.2, 1)
    incremental_rev = round(unrecovered_amt * (projected_lift_pct / 100.0), 2)
    additional_interventions = int(total_unrecovered * 0.35 * retry_delta)

    return {
        "tool_name": "simulate_policy_change",
        "current_policy": {"max_retry_attempts": 2, "cooldown_hours": 24},
        "proposed_policy": {"max_retry_attempts": proposed_max_retries, "cooldown_hours": proposed_cooldown_hours},
        "projected_simulation": {
            "estimated_recovery_lift_pct": f"+{projected_lift_pct}%",
            "estimated_incremental_recovery_inr": incremental_rev,
            "additional_interventions": additional_interventions,
            "risk_assessment": "Higher customer intervention touches. Exposure monitored by Governance."
        },
        "source": {"type": "recovery_simulator", "name": "Counterfactual Policy Simulator"}
    }


def request_automation_pause(
    db_path: str = "data/recover_ai.db",
    reason: str = "Manual pause requested via Copilot",
    actor: str = "ADMIN"
) -> Dict[str, Any]:
    """
    Generates a mutating action payload for pausing global automation.
    Requires explicit human confirmation before dispatching.
    """
    return {
        "tool_name": "request_automation_pause",
        "requires_confirmation": True,
        "action_type": "PAUSE_AUTOMATION",
        "target": "Global Automation Kill Switch",
        "details": f"Pause all automated recovery dispatches. Reason: {reason}",
        "actor": actor,
        "confirmation_prompt": "Are you sure you want to pause all automated recovery dispatches across RecoverAI?",
        "source": {"type": "policy_governance", "name": "Governance Kill Switch API"}
    }
