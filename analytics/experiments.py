"""
Recovery Experimentation & Strategy Comparison Framework for RecoverAI.
"""

import sqlite3
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4

from schema.attribution_schema import (
    ExperimentRecord,
    ExperimentCreateRequest,
)


def ensure_experiments_table_exists(db_path: str = "data/recover_ai.db") -> None:
    """Ensures experiments table exists and seeds 3 initial demo experiments if empty."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            segment TEXT NOT NULL,
            control_strategy TEXT NOT NULL,
            treatment_strategy TEXT NOT NULL,
            traffic_allocation TEXT NOT NULL,
            control_cases INTEGER NOT NULL,
            treatment_cases INTEGER NOT NULL,
            control_recovery_rate REAL NOT NULL,
            treatment_recovery_rate REAL NOT NULL,
            estimated_incremental_revenue REAL NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    cursor.execute("SELECT COUNT(*) FROM experiments;")
    cnt = cursor.fetchone()[0]

    if cnt == 0:
        now_str = datetime.utcnow().isoformat() + "Z"
        default_experiments = [
            (
                "exp_card_recovery_v1",
                "Failed Card Recovery v1",
                "payment_failure",
                "CARD",
                "RETRY_AFTER_24H",
                "PAYMENT_LINK_AFTER_30M",
                "50/50",
                1240, 1260,
                48.2, 63.7,
                342000.0,
                now_str
            ),
            (
                "exp_checkout_abandonment_v2",
                "Checkout Cart Abandonment v2",
                "checkout_abandonment",
                "ECOM_CHECKOUT",
                "NO_AUTOMATED_OUTREACH",
                "DISCOUNT_PAYMENT_LINK",
                "50/50",
                850, 875,
                28.5, 52.4,
                218000.0,
                now_str
            ),
            (
                "exp_saas_dunning_v1",
                "SaaS Subscription Dunning v1",
                "subscription_failure",
                "SAAS_RENEWAL",
                "AUTO_RETRY_CAP3",
                "MULTI_CHANNEL_DUNNING",
                "50/50",
                620, 640,
                42.1, 71.8,
                185000.0,
                now_str
            )
        ]

        cursor.executemany("""
            INSERT INTO experiments (
                experiment_id, name, event_type, segment, control_strategy,
                treatment_strategy, traffic_allocation, control_cases, treatment_cases,
                control_recovery_rate, treatment_recovery_rate, estimated_incremental_revenue,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, default_experiments)

    conn.commit()
    conn.close()


def get_all_experiments(db_path: str = "data/recover_ai.db") -> List[Dict[str, Any]]:
    """Returns list of active & completed recovery experiments with calculated lift metrics."""
    ensure_experiments_table_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM experiments ORDER BY created_at DESC;")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    result = []
    for r in rows:
        c_rate = float(r["control_recovery_rate"])
        t_rate = float(r["treatment_recovery_rate"])
        abs_lift = round(t_rate - c_rate, 1)
        rel_lift = round(((t_rate - c_rate) / c_rate * 100.0), 1) if c_rate > 0 else 0.0

        total_sample = int(r["control_cases"]) + int(r["treatment_cases"])
        confidence = "HIGH" if total_sample >= 1000 else ("MEDIUM" if total_sample >= 300 else "EARLY_SIGNAL")

        exp_rec = ExperimentRecord(
            experiment_id=r["experiment_id"],
            name=r["name"],
            event_type=r["event_type"],
            segment=r["segment"],
            control_strategy=r["control_strategy"],
            treatment_strategy=r["treatment_strategy"],
            traffic_allocation=r["traffic_allocation"],
            control_cases=int(r["control_cases"]),
            treatment_cases=int(r["treatment_cases"]),
            control_recovery_rate=c_rate,
            treatment_recovery_rate=t_rate,
            absolute_lift=abs_lift,
            relative_lift=rel_lift,
            estimated_incremental_revenue=float(r["estimated_incremental_revenue"]),
            confidence=confidence,
            created_at=r["created_at"]
        )
        result.append(exp_rec.dict())

    return result


def create_experiment(
    req: ExperimentCreateRequest,
    db_path: str = "data/recover_ai.db"
) -> Dict[str, Any]:
    """Creates a new recovery experiment in SQLite database."""
    ensure_experiments_table_exists(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    exp_id = f"exp_{uuid4().hex[:10]}"
    now_str = datetime.utcnow().isoformat() + "Z"

    # Initial baseline estimates for newly created experiment
    control_cases = 100
    treatment_cases = 100
    control_rate = 37.2
    treatment_rate = 58.5
    inc_revenue = 125000.0

    cursor.execute("""
        INSERT INTO experiments (
            experiment_id, name, event_type, segment, control_strategy,
            treatment_strategy, traffic_allocation, control_cases, treatment_cases,
            control_recovery_rate, treatment_recovery_rate, estimated_incremental_revenue,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        exp_id, req.name, req.event_type, req.segment, req.control_strategy,
        req.treatment_strategy, req.traffic_allocation, control_cases, treatment_cases,
        control_rate, treatment_rate, inc_revenue, now_str
    ))

    conn.commit()
    conn.close()

    return get_experiment_detail(exp_id, db_path=db_path)


def get_experiment_detail(
    experiment_id: str,
    db_path: str = "data/recover_ai.db"
) -> Dict[str, Any]:
    """Gets detailed metrics for a single experiment."""
    ensure_experiments_table_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM experiments WHERE experiment_id = ?;", (experiment_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Experiment '{experiment_id}' not found.")

    r = dict(row)
    c_rate = float(r["control_recovery_rate"])
    t_rate = float(r["treatment_recovery_rate"])
    abs_lift = round(t_rate - c_rate, 1)
    rel_lift = round(((t_rate - c_rate) / c_rate * 100.0), 1) if c_rate > 0 else 0.0

    total_sample = int(r["control_cases"]) + int(r["treatment_cases"])
    confidence = "HIGH" if total_sample >= 1000 else ("MEDIUM" if total_sample >= 300 else "EARLY_SIGNAL")

    return ExperimentRecord(
        experiment_id=r["experiment_id"],
        name=r["name"],
        event_type=r["event_type"],
        segment=r["segment"],
        control_strategy=r["control_strategy"],
        treatment_strategy=r["treatment_strategy"],
        traffic_allocation=r["traffic_allocation"],
        control_cases=int(r["control_cases"]),
        treatment_cases=int(r["treatment_cases"]),
        control_recovery_rate=c_rate,
        treatment_recovery_rate=t_rate,
        absolute_lift=abs_lift,
        relative_lift=rel_lift,
        estimated_incremental_revenue=float(r["estimated_incremental_revenue"]),
        confidence=confidence,
        created_at=r["created_at"]
    ).dict()
