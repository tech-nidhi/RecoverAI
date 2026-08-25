"""
Unit tests for RecoverAI Operations Copilot Engine, Backend Tools, Intent Classifier,
Hallucination Resistance, Governance Boundaries, and Confirmation Flow.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from agent.copilot_engine import process_copilot_query, classify_copilot_intent
from agent.copilot_tools import get_recovery_metrics, get_top_revenue_at_risk, simulate_policy_change

client = TestClient(app)


def test_intent_classifier():
    """Test intent classification rules."""
    assert classify_copilot_intent("Why did recovery drop today?") == "RECOVERY_ANALYSIS"
    assert classify_copilot_intent("What are the top 5 revenue-at-risk cases?") == "REVENUE_RISK"
    assert classify_copilot_intent("What happened to pay_demo_001?") == "TRANSACTION_TRACE"
    assert classify_copilot_intent("Why was this recovery blocked?") == "POLICY_EXPLANATION"
    assert classify_copilot_intent("Which recovery action performs best?") == "INTERVENTION_ANALYSIS"
    assert classify_copilot_intent("What happens if max retries increases from 2 to 3?") == "SIMULATION"
    assert classify_copilot_intent("Is RecoverAI healthy right now?") == "SYSTEM_HEALTH"
    assert classify_copilot_intent("Pause automation.") == "MUTATING_ACTION"
    assert classify_copilot_intent("What is the capital of France?") == "OUT_OF_SCOPE"


def test_copilot_recovery_analysis():
    """Test copilot recovery analysis query via process_copilot_query."""
    res = process_copilot_query("Why did recovery drop today?")
    assert res["intent"] == "RECOVERY_ANALYSIS"
    assert "incremental recovery" in res["answer"].lower() or "recovery" in res["answer"].lower()
    assert len(res["key_findings"]) >= 1
    assert "get_recovery_metrics" in res["tools_called"]


def test_copilot_revenue_risk():
    """Test copilot top revenue at risk cases query."""
    res = process_copilot_query("What are the top revenue-at-risk cases?")
    assert res["intent"] == "REVENUE_RISK"
    assert len(res["key_findings"]) >= 1
    assert "get_top_revenue_at_risk" in res["tools_called"]


def test_copilot_intervention_analysis():
    """Test copilot intervention performance query."""
    res = process_copilot_query("Which recovery action performs best?")
    assert res["intent"] == "INTERVENTION_ANALYSIS"
    assert "get_intervention_performance" in res["tools_called"]
    assert "baseline" in res["answer"].lower() or "performance" in res["answer"].lower()


def test_copilot_simulation():
    """Test counterfactual policy simulation via copilot."""
    res = process_copilot_query("What happens if max retries increases from 2 to 3?")
    assert res["intent"] == "SIMULATION"
    assert "simulate_policy_change" in res["tools_called"]
    assert "simulation_preview" in res
    assert res["simulation_preview"]["proposed_policy"]["max_retry_attempts"] == 3


def test_copilot_system_health():
    """Test system health check query."""
    res = process_copilot_query("Is RecoverAI healthy right now?")
    assert res["intent"] == "SYSTEM_HEALTH"
    assert "get_governance_status" in res["tools_called"]
    assert "operational" in res["answer"].lower() or "healthy" in res["answer"].lower()


def test_copilot_hallucination_resistance():
    """Test copilot handles non-existent transaction without inventing data."""
    res = process_copilot_query("What happened to pay_fake_nonexistent_999999?")
    assert res["intent"] == "TRANSACTION_TRACE"
    assert "couldn't find" in res["answer"].lower() or "not found" in res["answer"].lower()
    assert len(res["evidence"]) == 0


def test_copilot_governance_boundary():
    """Test copilot refuses to directly disable policy engine."""
    res = process_copilot_query("Disable all recovery policies.")
    assert "require explicit governance controls" in res["answer"].lower() or "cannot directly bypass" in res["answer"].lower()


def test_copilot_mutating_action_and_confirm_endpoint():
    """Test mutating action request returns requires_confirmation and /copilot/confirm endpoint works."""
    res = process_copilot_query("Pause automation.")
    assert res["intent"] == "MUTATING_ACTION"
    assert res["requires_confirmation"] is True

    # Test POST /copilot/confirm
    confirm_res = client.post("/copilot/confirm", json={"action_type": "PAUSE_AUTOMATION", "actor": "COPILOT_ADMIN"})
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "success"
    assert confirm_res.json()["global_automation_active"] is False

    # Restore active state for subsequent tests
    client.post("/governance/kill-switch", json={"active": True, "actor": "TEST_TEARDOWN"})


def test_copilot_api_endpoint():
    """Test POST /copilot/query REST API endpoint."""
    res = client.post("/copilot/query", json={"query": "Why did recovery change today?"})
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert "intent" in data
    assert "key_findings" in data
    assert "sources" in data
