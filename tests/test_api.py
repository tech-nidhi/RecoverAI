"""
Pytest Suite for RecoverAI FastAPI REST API Endpoints (Phase 5).

Verifies:
1. GET /summary returns top-level revenue, recovery rate, action counts, and policy override rates.
2. GET /cases returns paginated cases sorted by (amount * recovery_probability) DESC.
3. GET /cases/{event_id} returns detailed single event record with reasoning_text & policy decisions.
4. GET /simulator returns counterfactual strategy comparison scenarios vs actual policy routing.
"""

from fastapi.testclient import TestClient
import pytest

from backend.api import app

client = TestClient(app)


def test_get_summary():
    """Test GET /summary endpoint response structure & values."""
    response = client.get("/summary")
    assert response.status_code == 200
    data = response.json()

    assert "total_events" in data
    assert data["total_events"] >= 1000
    assert "total_revenue_at_risk" in data
    assert data["total_revenue_at_risk"] > 0
    assert "total_revenue_recovered" in data
    assert data["total_revenue_recovered"] > 0
    assert "overall_recovery_rate" in data
    assert 0.0 <= data["overall_recovery_rate"] <= 100.0
    assert "policy_override_rate" in data
    assert 0.0 <= data["policy_override_rate"] <= 100.0
    assert "action_distribution" in data
    assert isinstance(data["action_distribution"], dict)


def test_get_cases_pagination_and_sorting():
    """Test GET /cases pagination, ordering by (amount * recovery_probability) DESC."""
    response = client.get("/cases?page=1&limit=10")
    assert response.status_code == 200
    data = response.json()

    assert "cases" in data
    assert len(data["cases"]) == 10
    assert data["page"] == 1
    assert data["limit"] == 10
    assert data["total_cases"] >= 1000

    cases = data["cases"]
    # Check ordering by expected_recovery_value descending
    for i in range(len(cases) - 1):
        assert cases[i]["expected_recovery_value"] >= cases[i + 1]["expected_recovery_value"]


def test_get_cases_filtering():
    """Test GET /cases filtering by action and outcome."""
    response = client.get("/cases?action=RETRY&outcome=SUCCESS&limit=5")
    assert response.status_code == 200
    data = response.json()

    for c in data["cases"]:
        assert c["final_action"] == "RETRY"
        assert c["outcome"] == "SUCCESS"


def test_get_case_detail():
    """Test GET /cases/{event_id} returning full single record detail."""
    # First get a valid event_id from /cases
    list_resp = client.get("/cases?limit=1")
    event_id = list_resp.json()["cases"][0]["event_id"]

    detail_resp = client.get(f"/cases/{event_id}")
    assert detail_resp.status_code == 200
    data = detail_resp.json()

    assert data["event_id"] == event_id
    assert "customer_id" in data
    assert "amount" in data
    assert "recovery_probability" in data
    assert "recommended_action" in data
    assert "policy_decision" in data
    assert "reasoning_text" in data
    assert "outcome" in data
    assert "revenue_recovered" in data


def test_get_simulator():
    """Test GET /simulator counterfactual strategy comparison endpoint."""
    response = client.get("/simulator")
    assert response.status_code == 200
    data = response.json()

    assert "total_revenue_at_risk" in data
    assert "actual_revenue_recovered" in data
    assert "scenarios" in data
    assert len(data["scenarios"]) == 6  # 1 actual + 5 forced single strategies

    actual_scenario = data["scenarios"][0]
    assert actual_scenario["is_actual"] is True
    assert actual_scenario["strategy"] == "Actual RecoverAI Policy Routing"


def test_get_copilot_brief():
    """Test GET /copilot/brief endpoint response structure."""
    response = client.get("/copilot/brief")
    assert response.status_code == 200
    data = response.json()

    assert "metrics" in data
    assert "revenue_at_risk" in data["metrics"]
    assert "ai_priority_brief" in data
    assert "evidence" in data["ai_priority_brief"]
    assert "what_changed" in data
    assert "intervention_performance" in data
    assert "opportunity_map" in data
    assert "daily_action_plan" in data


def test_query_copilot():
    """Test POST /copilot/query operational copilot queries."""
    res1 = client.post("/copilot/query", json={"query": "Why did recovery drop this week?"})
    assert res1.status_code == 200
    d1 = res1.json()
    assert "answer" in d1
    assert "evidence" in d1

    res2 = client.post("/copilot/query", json={"query": "Why didn't RecoverAI retry this payment?"})
    assert res2.status_code == 200
    d2 = res2.json()
    assert "policy_explanation" in d2

    res3 = client.post("/copilot/query", json={"query": "What happens if I increase retries to 3?"})
    assert res3.status_code == 200
    d3 = res3.json()
    assert "simulation_preview" in d3

