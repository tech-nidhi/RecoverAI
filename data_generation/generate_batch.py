"""
Batch Synthetic Data Generator CLI for RecoverAI.

Generates N RevenueEvents sampled according to a configurable archetype mix weight,
and persists events to both a CSV file and SQLite database table ('revenue_events').
"""

import argparse
import csv
import json
import os
import random
import sqlite3
from typing import Dict, List, Optional, Union

from data_generation.archetypes import ARCHETYPES
from data_generation.generator import generate_event
from schema.event_schema import RevenueEvent


def generate_batch(
    n: int = 1000,
    archetype_mix: Optional[Dict[str, float]] = None,
    csv_path: Optional[str] = "data/revenue_events.csv",
    sqlite_path: Optional[str] = "data/recover_ai.db",
    seed: Optional[int] = None
) -> List[RevenueEvent]:
    """
    Generates n synthetic RevenueEvents according to archetype distribution weights,
    and saves them to CSV and SQLite database.

    Args:
        n: Number of events to generate.
        archetype_mix: Dict mapping archetype name -> sampling weight. If None, equal weights.
        csv_path: Path to output CSV file. Set to None to skip CSV export.
        sqlite_path: Path to SQLite DB file. Set to None to skip SQLite export.
        seed: Optional random seed for reproducible generation.

    Returns:
        List of generated RevenueEvent instances.
    """
    if seed is not None:
        random.seed(seed)

    # 1. Prepare archetype mix weights
    available_archetypes = list(ARCHETYPES.keys())
    if archetype_mix is None:
        weights = [1.0 / len(available_archetypes)] * len(available_archetypes)
        archetype_keys = available_archetypes
    else:
        archetype_keys = list(archetype_mix.keys())
        weights = list(archetype_mix.values())

    # 2. Sample archetypes and generate events
    sampled_archetypes = random.choices(archetype_keys, weights=weights, k=n)
    events: List[RevenueEvent] = [
        generate_event(arch_name) for arch_name in sampled_archetypes
    ]

    # 3. Save to CSV if path specified
    if csv_path:
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
        save_events_to_csv(events, csv_path)
        print(f"✓ Saved {len(events)} events to CSV: {csv_path}")

    # 4. Save to SQLite if path specified
    if sqlite_path:
        os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)
        save_events_to_sqlite(events, sqlite_path)
        print(f"✓ Saved {len(events)} events to SQLite DB ({sqlite_path}), table 'revenue_events'")

    return events


def save_events_to_csv(events: List[RevenueEvent], filepath: str) -> None:
    """Exports events to CSV file."""
    if not events:
        return

    fieldnames = [
        "event_id",
        "event_type",
        "timestamp",
        "amount",
        "customer_id",
        "failure_reason",
        "attempt_count",
        "days_since_last_attempt",
        "customer_history_summary",
        "archetype",
        "did_recover",
        "recovery_probability",
        "recommended_action",
        "policy_decision",
        "executed_action",
        "outcome",
        "revenue_recovered",
        "reasoning_text",
    ]

    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            row = event.model_dump(mode="json")
            # Serialize nested dict for CSV compatibility
            row["customer_history_summary"] = json.dumps(row["customer_history_summary"])
            writer.writerow(row)


def save_events_to_sqlite(events: List[RevenueEvent], db_path: str) -> None:
    """Exports events into SQLite table 'revenue_events'."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create table schema
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS revenue_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        amount REAL NOT NULL,
        customer_id TEXT NOT NULL,
        failure_reason TEXT,
        attempt_count INTEGER NOT NULL,
        days_since_last_attempt REAL NOT NULL,
        customer_history_summary TEXT NOT NULL,
        total_past_payments INTEGER NOT NULL,
        past_successful_payments INTEGER NOT NULL,
        past_recovery_rate REAL NOT NULL,
        archetype TEXT NOT NULL,
        did_recover INTEGER NOT NULL,
        recovery_probability REAL,
        recommended_action TEXT,
        policy_decision TEXT,
        executed_action TEXT,
        outcome TEXT,
        revenue_recovered REAL,
        reasoning_text TEXT
    );
    """)

    insert_sql = """
    INSERT OR REPLACE INTO revenue_events (
        event_id, event_type, timestamp, amount, customer_id,
        failure_reason, attempt_count, days_since_last_attempt,
        customer_history_summary, total_past_payments, past_successful_payments,
        past_recovery_rate, archetype, did_recover, recovery_probability,
        recommended_action, policy_decision, executed_action, outcome,
        revenue_recovered, reasoning_text
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rows = []
    for event in events:
        h = event.customer_history_summary
        rows.append((
            event.event_id,
            event.event_type,
            event.timestamp.isoformat(),
            event.amount,
            event.customer_id,
            event.failure_reason,
            event.attempt_count,
            event.days_since_last_attempt,
            json.dumps(h.model_dump()),
            h.total_past_payments,
            h.past_successful_payments,
            h.past_recovery_rate,
            event.archetype,
            1 if event.did_recover else 0,
            event.recovery_probability,
            event.recommended_action,
            event.policy_decision,
            event.executed_action,
            event.outcome,
            event.revenue_recovered,
            event.reasoning_text,
        ))

    cursor.executemany(insert_sql, rows)
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic payment revenue events for RecoverAI."
    )
    parser.add_argument(
        "-n", "--n", type=int, default=1000,
        help="Number of events to generate (default: 1000)"
    )
    parser.add_argument(
        "--mix", type=str, default=None,
        help="JSON string of archetype weights e.g. '{\"reliable_temporary_glitch\": 0.4, \"chronic_failer\": 0.6}'"
    )
    parser.add_argument(
        "--csv", type=str, default="data/revenue_events.csv",
        help="CSV file destination (default: data/revenue_events.csv)"
    )
    parser.add_argument(
        "--sqlite", type=str, default="data/recover_ai.db",
        help="SQLite database destination (default: data/recover_ai.db)"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for deterministic generation"
    )

    args = parser.parse_args()

    archetype_mix = None
    if args.mix:
        try:
            archetype_mix = json.loads(args.mix)
        except json.JSONDecodeError as e:
            print(f"Error parsing --mix JSON: {e}")
            return

    generate_batch(
        n=args.n,
        archetype_mix=archetype_mix,
        csv_path=args.csv,
        sqlite_path=args.sqlite,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
