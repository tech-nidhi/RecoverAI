"""
Decision Audit Log Module for RecoverAI (Phase 3).

Persists every LLM call's prompt, raw response, recommendation, reasoning text,
and policy evaluation result into SQLite table 'decisions'.
Serves as the audit log read by Phase 5 dashboards and compliance teams.
"""

from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import Optional
from uuid import uuid4

from agent.llm_agent import AgentDecision
from policy.policy_engine import PolicyEvaluationResult
from schema.event_schema import RevenueEvent


def init_decision_log_table(db_path: str = "data/recover_ai.db") -> None:
    """Initializes the SQLite 'decisions' table schema if it does not exist."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decisions (
        decision_id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        archetype TEXT NOT NULL,
        amount REAL NOT NULL,
        recovery_probability REAL,
        prompt_text TEXT NOT NULL,
        raw_llm_response TEXT NOT NULL,
        recommended_action TEXT NOT NULL,
        reasoning_text TEXT NOT NULL,
        approved INTEGER NOT NULL,
        blocking_rule TEXT,
        final_action TEXT NOT NULL,
        FOREIGN KEY (event_id) REFERENCES revenue_events (event_id)
    );
    """)

    conn.commit()
    conn.close()


def log_decision(
    event: RevenueEvent,
    agent_decision: AgentDecision,
    policy_result: PolicyEvaluationResult,
    prompt_text: Optional[str] = None,
    db_path: str = "data/recover_ai.db"
) -> str:
    """
    Persists an LLM decision and policy evaluation result to SQLite 'decisions' table.

    Returns:
        str: Unique decision_id UUID string.
    """
    init_decision_log_table(db_path)

    decision_id = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    raw_response = json.dumps(agent_decision.model_dump())
    prompt = prompt_text or f"Prompt for event {event.event_id}"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    insert_sql = """
    INSERT INTO decisions (
        decision_id, event_id, timestamp, customer_id, archetype,
        amount, recovery_probability, prompt_text, raw_llm_response,
        recommended_action, reasoning_text, approved, blocking_rule, final_action
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    cursor.execute(insert_sql, (
        decision_id,
        event.event_id,
        now_iso,
        event.customer_id,
        event.archetype,
        event.amount,
        event.recovery_probability,
        prompt,
        raw_response,
        agent_decision.recommended_action,
        agent_decision.reasoning_text,
        1 if policy_result.approved else 0,
        policy_result.blocking_rule,
        policy_result.final_action,
    ))

    conn.commit()
    conn.close()

    return decision_id
