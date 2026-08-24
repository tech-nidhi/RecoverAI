"""
Batch Event Processor CLI for RecoverAI (Phase 3).

Loads all RevenueEvents from SQLite/CSV, runs process_event() concurrently across all rows,
persists Phase 3 decisions back to SQLite, and prints summary metrics including action distribution
and archetype-level policy override rates.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sqlite3
from typing import Dict, List, Tuple
import pandas as pd

from agent.pipeline import process_event
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


def save_processed_events_to_sqlite(events: List[RevenueEvent], db_path: str = "data/recover_ai.db") -> None:
    """Updates Phase 3 fields (recommended_action, policy_decision, executed_action, reasoning_text) in SQLite."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    update_sql = """
    UPDATE revenue_events SET
        recommended_action = ?,
        policy_decision = ?,
        executed_action = ?,
        reasoning_text = ?
    WHERE event_id = ?
    """

    update_rows = [
        (
            e.recommended_action,
            e.policy_decision,
            e.executed_action,
            e.reasoning_text,
            e.event_id,
        )
        for e in events
    ]

    cursor.executemany(update_sql, update_rows)
    conn.commit()
    conn.close()
    print(f"✓ Updated Phase 3 fields in SQLite DB ({db_path}), table 'revenue_events'")


def update_csv_file(events: List[RevenueEvent], csv_path: str = "data/revenue_events.csv") -> None:
    """Updates CSV export file with Phase 3 fields."""
    if not os.path.exists(csv_path):
        return
    df = pd.read_csv(csv_path)
    
    # Cast target string columns to object dtype to prevent pandas LossySetitemError
    for col in ["recommended_action", "policy_decision", "executed_action", "reasoning_text"]:
        if col in df.columns:
            df[col] = df[col].astype(object)
        else:
            df[col] = None

    events_by_id = {e.event_id: e for e in events}

    for idx, row in df.iterrows():
        eid = row["event_id"]
        if eid in events_by_id:
            e = events_by_id[eid]
            df.loc[idx, "recommended_action"] = e.recommended_action
            df.loc[idx, "policy_decision"] = e.policy_decision
            df.loc[idx, "executed_action"] = e.executed_action
            df.loc[idx, "reasoning_text"] = e.reasoning_text

    df.to_csv(csv_path, index=False)
    print(f"✓ Updated Phase 3 fields in CSV: {csv_path}")


def run_batch_pipeline(
    db_path: str = "data/recover_ai.db",
    csv_path: str = "data/revenue_events.csv",
    max_workers: int = 10,
    report_path: str = "reports/policy_override_analysis.md"
) -> List[RevenueEvent]:
    """
    Executes Phase 3 processing pipeline concurrently across all events in SQLite.
    """
    print(f"Loading events from SQLite database: {db_path}...")
    events = load_events_from_sqlite(db_path)
    total_events = len(events)
    print(f"Loaded {total_events} events. Processing through LLM Agent & Policy Engine with max_workers={max_workers}...")

    processed_events: List[RevenueEvent] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_event = {
            executor.submit(process_event, event, None, db_path): event
            for event in events
        }
        for future in as_completed(future_to_event):
            try:
                updated_event = future.result()
                processed_events.append(updated_event)
            except Exception as e:
                orig_event = future_to_event[future]
                print(f"[Error] Failed processing event {orig_event.event_id}: {e}")

    # Persist updated event records
    save_processed_events_to_sqlite(processed_events, db_path)
    update_csv_file(processed_events, csv_path)

    # Compute & Print Summary Statistics
    print_summary_statistics(processed_events, report_path)

    return processed_events


def print_summary_statistics(events: List[RevenueEvent], report_path: str = "reports/policy_override_analysis.md") -> None:
    """Computes and prints action distributions and archetype-level policy override rates."""
    total = len(events)
    if total == 0:
        print("No events processed.")
        return

    # 1. Action Distribution (Count per executed_action)
    action_counts: Dict[str, int] = {}
    for e in events:
        act = e.executed_action or "UNKNOWN"
        action_counts[act] = action_counts.get(act, 0) + 1

    # 2. Policy Override Metrics
    blocked_count = sum(1 for e in events if e.policy_decision and e.policy_decision.startswith("BLOCKED"))
    override_rate = (blocked_count / total) * 100.0

    # 3. Archetype Breakdown
    archetype_stats: Dict[str, Dict[str, int]] = {}
    for e in events:
        arch = e.archetype
        if arch not in archetype_stats:
            archetype_stats[arch] = {"total": 0, "approved": 0, "blocked": 0}
        archetype_stats[arch]["total"] += 1
        if e.policy_decision and e.policy_decision.startswith("BLOCKED"):
            archetype_stats[arch]["blocked"] += 1
        else:
            archetype_stats[arch]["approved"] += 1

    # Print to console
    print("\n==================================================")
    print("      PHASE 3: ACTION DISTRIBUTION SUMMARY        ")
    print("==================================================")
    print(f"{'Final Executed Action':<25} | {'Count':<8} | {'Percentage'}")
    print("-" * 52)
    for act, count in sorted(action_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"{act:<25} | {count:<8} | {count/total*100:.1f}%")

    print("\n==================================================")
    print("         POLICY ENGINE OVERRIDE ANALYSIS          ")
    print("==================================================")
    print(f"Total Processed Events     : {total}")
    print(f"Approved LLM Decisions    : {total - blocked_count} ({(total - blocked_count)/total*100:.1f}%)")
    print(f"Blocked Policy Overrides  : {blocked_count} ({override_rate:.1f}%)")

    print("\n--------------------------------------------------")
    print("   OVERRIDE RATE BREAKDOWN BY CUSTOMER ARCHETYPE  ")
    print("--------------------------------------------------")
    print(f"{'Archetype Name':<28} | {'Total':<6} | {'Approved':<8} | {'Blocked':<8} | {'Override Rate'}")
    print("-" * 72)
    for arch, stats in sorted(archetype_stats.items()):
        o_rate = (stats["blocked"] / stats["total"]) * 100.0 if stats["total"] > 0 else 0.0
        print(f"{arch:<28} | {stats['total']:<6} | {stats['approved']:<8} | {stats['blocked']:<8} | {o_rate:.1f}%")

    # Generate Markdown Analysis Report
    generate_override_report(events, action_counts, blocked_count, override_rate, archetype_stats, report_path)


def generate_override_report(
    events: List[RevenueEvent],
    action_counts: dict,
    blocked_count: int,
    override_rate: float,
    archetype_stats: dict,
    report_path: str
) -> None:
    """Generates reports/policy_override_analysis.md."""
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    total = len(events)

    md_content = f"""# RecoverAI - Policy Override Analysis & Agent Decision Report (Phase 3)

This report details the operational performance, action distributions, and deterministic policy guardrail overrides for **RecoverAI Phase 3**.

---

## 1. Executive Summary

- **Total Events Processed**: `{total}`
- **Approved LLM Recommendations**: `{total - blocked_count}` ({(total - blocked_count)/total*100:.1f}%)
- **Policy Engine Overrides (Blocked)**: `{blocked_count}` (**{override_rate:.1f}%**)

> **Key Takeaway**: The policy engine successfully prevented unsafe, non-compliant, or economically unviable AI recommendations in **{override_rate:.1f}%** of events, enforcing regulatory compliance (RBI 2FA, TRAI anti-spam) and financial guardrails.

---

## 2. Final Executed Action Distribution

| Final Executed Action | Event Count | Share of Total | Primary Intent |
| :--- | :---: | :---: | :--- |
"""
    for act, count in sorted(action_counts.items(), key=lambda x: x[1], reverse=True):
        md_content += f"| `{act}` | {count} | `{count/total*100:.1f}%` | Standard recovery action |\n"

    md_content += """
---

## 3. Policy Override Breakdown by Archetype

| Customer Archetype | Total Events | Approved | Blocked (Overridden) | Policy Override Rate | Primary Guardrail Triggered |
| :--- | :---: | :---: | :---: | :---: | :--- |
"""
    for arch, stats in sorted(archetype_stats.items()):
        o_rate = (stats["blocked"] / stats["total"]) * 100.0 if stats["total"] > 0 else 0.0
        md_content += (
            f"| `{arch}` | {stats['total']} | {stats['approved']} | {stats['blocked']} | "
            f"**`{o_rate:.1f}%`** | Hard policy constraint |\n"
        )

    md_content += """
---

## 4. Policy Guardrail Architecture

The system strictly decouples **AI Recommendation Generation** from **Policy Enforcement**:
1. **LLM Agent (`agent/llm_agent.py`)**: Proposes `recommended_action` and 2-3 sentence reasoning text.
2. **Policy Engine (`policy/policy_engine.py`)**: Evaluates `policy/rules.yaml` rules deterministically. If blocked, substitutes a safe fallback `final_action`.
3. **Audit Log (`agent/decision_log.py`)**: Records every decision into SQLite table `decisions`.
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n✓ Generated policy override analysis report at: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Process RevenueEvents through RecoverAI LLM Agent and Policy Engine.")
    parser.add_argument("--db", type=str, default="data/recover_ai.db", help="Path to SQLite database")
    parser.add_argument("--csv", type=str, default="data/revenue_events.csv", help="Path to CSV export file")
    parser.add_argument("--workers", type=int, default=10, help="Number of concurrent worker threads")

    args = parser.parse_args()
    run_batch_pipeline(db_path=args.db, csv_path=args.csv, max_workers=args.workers)


if __name__ == "__main__":
    main()
