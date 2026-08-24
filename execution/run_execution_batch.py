"""
Batch Action Execution CLI for RecoverAI (Phase 4).

Loads all Phase 3 processed events, executes approved actions concurrently via Razorpay SDK/simulators,
persists outcome ('SUCCESS', 'FAILED', 'PENDING', 'NO_ACTION') and revenue_recovered to SQLite,
and computes empirical financial recovery metrics.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sqlite3
import time
from typing import List, Optional
import pandas as pd

from execution.executor import execute_action
from execution.metrics import compute_execution_metrics
from schema.event_schema import CustomerHistorySummary, RevenueEvent


def load_events_from_sqlite(db_path: str = "data/recover_ai.db") -> List[RevenueEvent]:
    """Loads all revenue events from SQLite database table 'revenue_events'."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM revenue_events;")
    rows = cursor.fetchall()
    conn.close()

    events = []
    for row in rows:
        r = dict(row)
        # Parse history summary
        if r.get("customer_history_summary"):
            try:
                hist_dict = json.loads(r["customer_history_summary"])
            except Exception:
                hist_dict = {
                    "total_past_payments": r.get("total_past_payments", 0),
                    "past_successful_payments": r.get("past_successful_payments", 0),
                    "past_recovery_rate": r.get("past_recovery_rate", 0.0),
                }
        else:
            hist_dict = {
                "total_past_payments": r.get("total_past_payments", 0),
                "past_successful_payments": r.get("past_successful_payments", 0),
                "past_recovery_rate": r.get("past_recovery_rate", 0.0),
            }

        hist_summary = CustomerHistorySummary(**hist_dict)

        event = RevenueEvent(
            event_id=r["event_id"],
            event_type=r["event_type"],
            timestamp=r["timestamp"],
            amount=r["amount"],
            customer_id=r["customer_id"],
            failure_reason=r.get("failure_reason"),
            attempt_count=r["attempt_count"],
            days_since_last_attempt=r["days_since_last_attempt"],
            customer_history_summary=hist_summary,
            archetype=r["archetype"],
            did_recover=bool(r["did_recover"]),
            recovery_probability=r.get("recovery_probability"),
            recommended_action=r.get("recommended_action"),
            policy_decision=r.get("policy_decision"),
            executed_action=r.get("executed_action"),
            outcome=r.get("outcome"),
            revenue_recovered=r.get("revenue_recovered"),
            reasoning_text=r.get("reasoning_text"),
        )
        events.append(event)

    return events


def save_execution_results_to_sqlite(events: List[RevenueEvent], db_path: str = "data/recover_ai.db") -> None:
    """Updates Phase 4 fields (outcome, revenue_recovered) in SQLite."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    update_sql = """
    UPDATE revenue_events SET
        outcome = ?,
        revenue_recovered = ?
    WHERE event_id = ?
    """

    update_rows = [
        (
            e.outcome,
            e.revenue_recovered,
            e.event_id,
        )
        for e in events
    ]

    cursor.executemany(update_sql, update_rows)
    conn.commit()
    conn.close()
    print(f"✓ Updated execution outcome & revenue_recovered in SQLite DB ({db_path}), table 'revenue_events'")


def update_csv_file(events: List[RevenueEvent], csv_path: str = "data/revenue_events.csv") -> None:
    """Updates CSV export file with Phase 4 fields."""
    if not os.path.exists(csv_path):
        return
    df = pd.read_csv(csv_path)

    # Ensure outcome and revenue_recovered columns are string/float
    df["outcome"] = df["outcome"].astype(object)
    df["revenue_recovered"] = df["revenue_recovered"].astype(float)

    events_by_id = {e.event_id: e for e in events}

    for idx, row in df.iterrows():
        eid = row["event_id"]
        if eid in events_by_id:
            e = events_by_id[eid]
            df.loc[idx, "outcome"] = e.outcome
            df.loc[idx, "revenue_recovered"] = e.revenue_recovered

    df.to_csv(csv_path, index=False)
    print(f"✓ Updated Phase 4 fields in CSV: {csv_path}")


def _execute_with_retry(event: RevenueEvent, max_retries: int = 2) -> RevenueEvent:
    """Helper executing action with basic retry handling around API calls."""
    for attempt in range(max_retries + 1):
        try:
            return execute_action(event)
        except Exception as e:
            if attempt == max_retries:
                print(f"[Error] Execution failed for event {event.event_id} after {max_retries} retries: {e}")
                event.outcome = "FAILED"
                event.revenue_recovered = 0.0
                return event
            time.sleep(0.1 * (attempt + 1))


def run_execution_batch(
    db_path: str = "data/recover_ai.db",
    csv_path: str = "data/revenue_events.csv",
    max_workers: int = 10,
    report_path: str = "reports/execution_metrics.md"
) -> List[RevenueEvent]:
    """
    Executes approved actions across all events in SQLite and computes metrics.
    """
    print(f"Loading Phase 3 events from SQLite database: {db_path}...")
    events = load_events_from_sqlite(db_path)
    total_events = len(events)
    print(f"Loaded {total_events} events. Executing approved actions with max_workers={max_workers}...")

    executed_events: List[RevenueEvent] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_event = {
            executor.submit(_execute_with_retry, event): event
            for event in events
        }
        for future in as_completed(future_to_event):
            try:
                updated_event = future.result()
                executed_events.append(updated_event)
            except Exception as e:
                orig_event = future_to_event[future]
                print(f"[Error] Exception executing event {orig_event.event_id}: {e}")

    # Persist updated event outcomes
    save_execution_results_to_sqlite(executed_events, db_path)
    update_csv_file(executed_events, csv_path)

    # Compute & Print Financial Metrics
    compute_execution_metrics(db_path=db_path, report_path=report_path)

    return executed_events


def main():
    parser = argparse.ArgumentParser(description="Execute approved recovery actions via Razorpay gateway.")
    parser.add_argument("--db", type=str, default="data/recover_ai.db", help="Path to SQLite database")
    parser.add_argument("--csv", type=str, default="data/revenue_events.csv", help="Path to CSV export file")
    parser.add_argument("--workers", type=int, default=10, help="Number of concurrent worker threads")

    args = parser.parse_args()
    run_execution_batch(db_path=args.db, csv_path=args.csv, max_workers=args.workers)


if __name__ == "__main__":
    main()
