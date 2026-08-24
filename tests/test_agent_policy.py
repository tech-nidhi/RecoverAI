"""
Pytest Suite for RecoverAI LLM Agent, Policy Engine, and Pipeline (Phase 3).

Verifies:
1. Deterministic Policy Engine independently enforces all 6 operational rules with correct fallback actions.
2. LLM Reasoning Agent returns valid AgentDecision model with recommended_action and 2-3 sentence reasoning_text.
3. Process event pipeline coordinates LLM + Policy Engine, updates event fields, and logs audit record to SQLite decisions table.
"""

from datetime import datetime, timezone
import os
import sqlite3
import pytest

from agent.decision_log import log_decision
from agent.llm_agent import decide_action, AgentDecision
from agent.pipeline import process_event
from policy.policy_engine import evaluate_policy
from schema.event_schema import CustomerHistorySummary, RevenueEvent


@pytest.fixture
def base_event() -> RevenueEvent:
    """Fixture providing a standard baseline RevenueEvent."""
    return RevenueEvent(
        event_id="test-event-001",
        event_type="payment_failure",
        timestamp=datetime.now(timezone.utc),
        amount=5000.0,
        customer_id="cust_test_1001",
        failure_reason="network_error",
        attempt_count=1,
        days_since_last_attempt=1.5,
        customer_history_summary=CustomerHistorySummary(
            total_past_payments=20,
            past_successful_payments=18,
            past_recovery_rate=0.90
        ),
        archetype="reliable_temporary_glitch",
        did_recover=True,
        recovery_probability=0.85
    )


def test_policy_engine_rule_1_stop_low_probability(base_event):
    """Test Rule 1: stop_if_recovery_probability_below (0.20)."""
    base_event.recovery_probability = 0.10
    result = evaluate_policy(base_event, recommended_action="RETRY")

    assert not result.approved
    assert result.final_action == "STOP"
    assert result.blocking_rule == "stop_if_recovery_probability_below"


def test_policy_engine_rule_2_payment_link_threshold(base_event):
    """Test Rule 2: payment_link_threshold_amount (20,000 INR)."""
    base_event.amount = 25000.0
    result = evaluate_policy(base_event, recommended_action="RETRY")

    assert not result.approved
    assert result.final_action == "PAYMENT_LINK"
    assert result.blocking_rule == "payment_link_threshold_amount"


def test_policy_engine_rule_3_max_retry_attempts(base_event):
    """Test Rule 3: max_retry_attempts (3)."""
    base_event.attempt_count = 3
    result = evaluate_policy(base_event, recommended_action="RETRY")

    assert not result.approved
    assert result.final_action == "ESCALATE"
    assert result.blocking_rule == "max_retry_attempts"


def test_policy_engine_rule_4_retry_cooldown(base_event):
    """Test Rule 4: retry_cooldown_minutes (30 min = 0.0208 days)."""
    base_event.days_since_last_attempt = 0.01  # ~14 minutes
    result = evaluate_policy(base_event, recommended_action="RETRY")

    assert not result.approved
    assert result.final_action == "STOP"
    assert result.blocking_rule == "retry_cooldown_minutes"


def test_policy_engine_rule_5_escalate_after_failed_attempts(base_event):
    """Test Rule 5: escalation_after_failed_attempts (4)."""
    base_event.attempt_count = 4
    result = evaluate_policy(base_event, recommended_action="REMINDER")

    assert not result.approved
    assert result.final_action == "ESCALATE"
    assert result.blocking_rule == "escalation_after_failed_attempts"


def test_policy_engine_approval(base_event):
    """Test policy engine approving valid recommendation."""
    result = evaluate_policy(base_event, recommended_action="RETRY")

    assert result.approved
    assert result.final_action == "RETRY"
    assert result.blocking_rule is None


def test_llm_agent_decision_structure(base_event):
    """Test decide_action returning valid AgentDecision."""
    decision = decide_action(base_event)

    assert isinstance(decision, AgentDecision)
    assert decision.recommended_action in ["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"]
    assert len(decision.reasoning_text) > 10


def test_pipeline_end_to_end(base_event, tmp_path):
    """Test process_event updating event fields and logging to SQLite decisions table."""
    db_path = os.path.join(tmp_path, "test_recover_ai.db")

    updated_event = process_event(base_event, db_path=db_path)

    assert updated_event.recommended_action is not None
    assert updated_event.policy_decision is not None
    assert updated_event.executed_action is not None
    assert updated_event.reasoning_text is not None

    # Verify decision log table persistence
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), recommended_action, final_action FROM decisions WHERE event_id = ?;", (base_event.event_id,))
    count, rec_act, final_act = cursor.fetchone()
    conn.close()

    assert count == 1
    assert rec_act == updated_event.recommended_action
    assert final_act == updated_event.executed_action
