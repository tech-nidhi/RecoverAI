"""
Incremental ROI Attribution & Financial Impact Analytics Engine for RecoverAI.
"""

import sqlite3
import os
from typing import Dict, Any, List, Optional

from schema.attribution_schema import (
    AttributionMetrics,
    InterventionPerformance,
    EventTypePerformance,
    CaseAttributionTrace,
)


SEGMENT_BASELINE_RATES: Dict[str, float] = {
    "payment_failure": 0.372,
    "checkout_abandonment": 0.285,
    "subscription_failure": 0.421,
    "overdue_invoice": 0.310,
    "default": 0.350
}

ACTION_EXECUTION_COSTS: Dict[str, float] = {
    "PAYMENT_LINK": 0.50,
    "REMINDER": 0.20,
    "RETRY": 0.10,
    "ESCALATE": 12.00,
    "STOP": 0.00,
    "UNKNOWN": 0.00
}

EVENT_TYPE_LABELS: Dict[str, str] = {
    "payment_failure": "PAYMENT FAILURE",
    "checkout_abandonment": "CHECKOUT ABANDONMENT",
    "subscription_failure": "SUBSCRIPTION FAILURE",
    "overdue_invoice": "OVERDUE INVOICE"
}


def get_baseline_rate(event_type: str) -> float:
    """Returns historical organic baseline recovery rate for a given category."""
    clean_type = (event_type or "").strip().lower()
    return SEGMENT_BASELINE_RATES.get(clean_type, SEGMENT_BASELINE_RATES["default"])


def get_execution_cost(action: str) -> float:
    """Returns configured execution cost for a given intervention action."""
    clean_act = (action or "").strip().upper()
    return ACTION_EXECUTION_COSTS.get(clean_act, 0.0)


def compute_recovery_impact_metrics(
    db_path: str = "data/recover_ai.db",
    category: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None
) -> Dict[str, Any]:
    """
    Authoritative backend calculation for RecoverAI Incremental ROI and Attribution Metrics.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    conditions = []
    params = []

    if category and category.strip() and category.upper() != "ALL":
        cat_val = category.strip().lower().replace(" ", "_")
        conditions.append("event_type LIKE ?")
        params.append(f"%{cat_val}%")

    if action and action.strip() and action.upper() != "ALL":
        conditions.append("executed_action = ?")
        params.append(action.strip().upper())

    if search and search.strip():
        s = search.strip()
        conditions.append("(customer_id LIKE ? OR event_id LIKE ? OR event_type LIKE ? OR failure_reason LIKE ?)")
        params.extend([f"%{s}%", f"%{s}%", f"%{s}%", f"%{s}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cursor.execute(f"SELECT * FROM revenue_events {where_clause};", params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return {
            "metrics": AttributionMetrics(
                total_revenue_at_risk=0.0,
                total_recovered=0.0,
                estimated_baseline_recovery=0.0,
                estimated_incremental_recovery=0.0,
                recovery_lift_percent=0.0,
                execution_cost=0.0,
                net_incremental_value=0.0,
                estimated_roi=0.0
            ).dict(),
            "interventions": [],
            "event_types": []
        }

    total_risk = 0.0
    total_recovered = 0.0
    total_baseline = 0.0
    total_execution_cost = 0.0

    # Dictionaries for intervention and event_type breakdown
    action_groups: Dict[str, Dict[str, Any]] = {}
    event_groups: Dict[str, Dict[str, Any]] = {}

    for r in rows:
        amt = float(r.get("amount") or 0.0)
        rec = float(r.get("revenue_recovered") or 0.0) if r.get("outcome") == "SUCCESS" else 0.0
        ev_type = str(r.get("event_type") or "payment_failure").strip().lower()
        act = str(r.get("executed_action") or "UNKNOWN").strip().upper()

        base_rate = get_baseline_rate(ev_type)
        base_recovery = amt * base_rate
        cost = get_execution_cost(act)

        total_risk += amt
        total_recovered += rec
        total_baseline += base_recovery
        total_execution_cost += cost

        # Group by Action
        if act not in action_groups:
            action_groups[act] = {"cases": 0, "recovered": 0.0, "baseline": 0.0, "cost": 0.0, "risk": 0.0}
        action_groups[act]["cases"] += 1
        action_groups[act]["recovered"] += rec
        action_groups[act]["baseline"] += base_recovery
        action_groups[act]["cost"] += cost
        action_groups[act]["risk"] += amt

        # Group by Event Type
        if ev_type not in event_groups:
            event_groups[ev_type] = {"cases": 0, "risk": 0.0, "recovered": 0.0, "baseline": 0.0}
        event_groups[ev_type]["cases"] += 1
        event_groups[ev_type]["risk"] += amt
        event_groups[ev_type]["recovered"] += rec
        event_groups[ev_type]["baseline"] += base_recovery

    # Top-Level Derived Calculations
    incremental_recovery = max(0.0, total_recovered - total_baseline)
    lift_percent = ((total_recovered - total_baseline) / total_baseline * 100.0) if total_baseline > 0 else 0.0
    net_value = max(0.0, incremental_recovery - total_execution_cost)
    roi = (net_value / total_execution_cost) if total_execution_cost > 0 else 0.0

    metrics = AttributionMetrics(
        total_revenue_at_risk=round(total_risk, 2),
        total_recovered=round(total_recovered, 2),
        estimated_baseline_recovery=round(total_baseline, 2),
        estimated_incremental_recovery=round(incremental_recovery, 2),
        recovery_lift_percent=round(lift_percent, 1),
        execution_cost=round(total_execution_cost, 2),
        net_incremental_value=round(net_value, 2),
        estimated_roi=round(roi, 1)
    )

    # Build Intervention Performance List
    interventions_list: List[Dict[str, Any]] = []
    for act, g in action_groups.items():
        if act in ["UNKNOWN", "STOP"]:
            continue
        inc_rec = max(0.0, g["recovered"] - g["baseline"])
        act_lift = ((g["recovered"] - g["baseline"]) / g["baseline"] * 100.0) if g["baseline"] > 0 else 0.0
        obs_rate = (g["recovered"] / g["risk"] * 100.0) if g["risk"] > 0 else 0.0
        base_rate = (g["baseline"] / g["risk"] * 100.0) if g["risk"] > 0 else 35.0

        confidence = "HIGH" if g["cases"] >= 50 else ("MEDIUM" if g["cases"] >= 15 else "EARLY_SIGNAL")

        interventions_list.append(InterventionPerformance(
            action=act,
            cases=g["cases"],
            recovered=round(g["recovered"], 2),
            estimated_baseline=round(g["baseline"], 2),
            estimated_incremental=round(inc_rec, 2),
            lift_percent=round(act_lift, 1),
            observed_rate=round(obs_rate, 1),
            baseline_rate=round(base_rate, 1),
            sample_size=g["cases"],
            confidence=confidence
        ).dict())

    interventions_list.sort(key=lambda x: x["estimated_incremental"], reverse=True)

    # Build Event Type Performance List
    event_types_list: List[Dict[str, Any]] = []
    for ev_type, g in event_groups.items():
        inc_rec = max(0.0, g["recovered"] - g["baseline"])
        rec_rate = (g["recovered"] / g["risk"] * 100.0) if g["risk"] > 0 else 0.0
        label = EVENT_TYPE_LABELS.get(ev_type, ev_type.upper().replace("_", " "))

        event_types_list.append(EventTypePerformance(
            event_type=ev_type,
            label=label,
            cases=g["cases"],
            revenue_at_risk=round(g["risk"], 2),
            recovered=round(g["recovered"], 2),
            estimated_baseline=round(g["baseline"], 2),
            estimated_incremental=round(inc_rec, 2),
            recovery_rate=round(rec_rate, 1)
        ).dict())

    event_types_list.sort(key=lambda x: x["estimated_incremental"], reverse=True)

    return {
        "metrics": metrics.dict(),
        "interventions": interventions_list,
        "event_types": event_types_list
    }


def get_transaction_attribution_trace(
    event_id: str,
    db_path: str = "data/recover_ai.db"
) -> CaseAttributionTrace:
    """Calculates transaction-level attribution details for a specific case."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM revenue_events WHERE event_id = ?;", (event_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Case '{event_id}' not found.")

    r = dict(row)
    amt = float(r.get("amount") or 0.0)
    rec = float(r.get("revenue_recovered") or 0.0) if r.get("outcome") == "SUCCESS" else 0.0
    ev_type = str(r.get("event_type") or "payment_failure").strip().lower()
    act = str(r.get("executed_action") or "PAYMENT_LINK").strip().upper()

    base_rate = get_baseline_rate(ev_type)
    base_recovery = round(amt * base_rate, 2)
    inc_recovery = round(max(0.0, rec - base_recovery), 2)
    cost = get_execution_cost(act)
    net_val = round(inc_recovery - cost, 2)
    prob = round(float(r.get("recovery_probability") or 0.85), 4)

    return CaseAttributionTrace(
        event_id=event_id,
        customer_id=str(r.get("customer_id") or "unknown"),
        amount_at_risk=amt,
        observed_recovery=rec,
        baseline_probability=base_rate,
        estimated_baseline_recovery=base_recovery,
        estimated_incremental_recovery=inc_recovery,
        intervention=act,
        execution_cost=cost,
        net_incremental_value=net_val,
        recoverai_probability=prob,
        policy_version="policy_v2_2026"
    )
