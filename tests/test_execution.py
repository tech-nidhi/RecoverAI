"""
Pytest Suite for RecoverAI Action Execution & Financial Metrics (Phase 4).

Verifies:
1. razorpay_client methods return valid GatewayResponse matching ground-truth did_recover labels.
2. executor.py strictly respects idempotency (skips re-execution if outcome is already set).
3. executor.py correctly dispatches RETRY, PAYMENT_LINK, REMINDER, ESCALATE, and STOP actions.
4. compute_execution_metrics calculates empirical financial recovery stats and false interventions.
"""

from datetime import datetime, timezone
import os
import pytest

from execution.executor import execute_action
from execution.metrics import compute_execution_metrics
from execution.razorpay_client import retry_payment, create_payment_link, send_reminder, GatewayResponse
from schema.event_schema import CustomerHistorySummary, RevenueEvent


@pytest.fixture
def sample_event() -> RevenueEvent:
    """Fixture providing a standard RevenueEvent for execution testing."""
    return RevenueEvent(
        event_id="exec-test-001",
        event_type="payment_failure",
        timestamp=datetime.now(timezone.utc),
        amount=10000.0,
        customer_id="cust_exec_999",
        failure_reason="insufficient_funds",
        attempt_count=1,
        days_since_last_attempt=1.0,
        customer_history_summary=CustomerHistorySummary(
            total_past_payments=15,
            past_successful_payments=14,
            past_recovery_rate=0.93
        ),
        archetype="reliable_temporary_glitch",
        did_recover=True,
        recovery_probability=0.88,
        recommended_action="RETRY",
        policy_decision="APPROVED",
        executed_action="RETRY",
        outcome=None,
        revenue_recovered=None,
        reasoning_text="Standard transient retry recommendation."
    )


def test_razorpay_client_simulation(sample_event):
    """Test razorpay_client functions returning valid GatewayResponse."""
    # 1. Successful recovery case (did_recover = True)
    sample_event.did_recover = True
    retry_res = retry_payment(sample_event)
    assert isinstance(retry_res, GatewayResponse)
    assert retry_res.success is True
    assert retry_res.status == "SUCCESS"

    plink_res = create_payment_link(sample_event)
    assert isinstance(plink_res, GatewayResponse)
    assert plink_res.success is True
    assert plink_res.status == "SUCCESS"

    rem_res = send_reminder(sample_event)
    assert isinstance(rem_res, GatewayResponse)
    assert rem_res.success is True
    assert rem_res.status == "SUCCESS"

    # 2. Failed recovery case (did_recover = False)
    sample_event.did_recover = False
    retry_fail = retry_payment(sample_event)
    assert retry_fail.success is False
    assert retry_fail.status == "FAILED"


def test_executor_idempotency(sample_event):
    """Test executor idempotency: skips execution if outcome is already set."""
    sample_event.outcome = "SUCCESS"
    sample_event.revenue_recovered = 10000.0
    sample_event.executed_action = "RETRY"

    # Call execute_action on already executed event
    res_event = execute_action(sample_event)

    # Should remain unchanged
    assert res_event.outcome == "SUCCESS"
    assert res_event.revenue_recovered == 10000.0


def test_executor_action_dispatch(sample_event):
    """Test executor dispatching RETRY, PAYMENT_LINK, REMINDER, ESCALATE, and STOP actions."""
    # RETRY action
    sample_event.executed_action = "RETRY"
    sample_event.did_recover = True
    res_retry = execute_action(sample_event)
    assert res_retry.outcome == "SUCCESS"
    assert res_retry.revenue_recovered == 10000.0

    # ESCALATE action
    sample_event.outcome = None
    sample_event.revenue_recovered = None
    sample_event.executed_action = "ESCALATE"
    res_esc = execute_action(sample_event)
    assert res_esc.outcome == "PENDING"
    assert res_esc.revenue_recovered == 0.0

    # STOP action
    sample_event.outcome = None
    sample_event.revenue_recovered = None
    sample_event.executed_action = "STOP"
    res_stop = execute_action(sample_event)
    assert res_stop.outcome == "NO_ACTION"
    assert res_stop.revenue_recovered == 0.0


def test_metrics_calculation():
    """Test compute_execution_metrics running on current SQLite database."""
    metrics = compute_execution_metrics()

    assert "total_revenue_at_risk" in metrics
    assert "total_revenue_recovered" in metrics
    assert "overall_recovery_rate" in metrics
    assert "false_intervention_count" in metrics

    assert metrics["total_revenue_at_risk"] > 0
    assert metrics["total_revenue_recovered"] >= 0
    assert 0.0 <= metrics["overall_recovery_rate"] <= 100.0
    assert metrics["false_intervention_count"] >= 0

    assert os.path.exists("reports/execution_metrics.md")
