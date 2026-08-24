"""
Unit tests for Incremental ROI Attribution, Baseline Recovery, and Recovery Intelligence.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from analytics.attribution import (
    compute_recovery_impact_metrics,
    get_transaction_attribution_trace,
    get_baseline_rate,
    get_execution_cost,
)

client = TestClient(app)


def test_baseline_rate_lookup():
    """Test baseline organic recovery rates per leakage category."""
    assert get_baseline_rate("payment_failure") == 0.372
    assert get_baseline_rate("checkout_abandonment") == 0.285
    assert get_baseline_rate("subscription_failure") == 0.421
    assert get_baseline_rate("overdue_invoice") == 0.310
    assert get_baseline_rate("unknown") == 0.350


def test_execution_cost_lookup():
    """Test configured execution costs per intervention action."""
    assert get_execution_cost("PAYMENT_LINK") == 0.50
    assert get_execution_cost("REMINDER") == 0.20
    assert get_execution_cost("RETRY") == 0.10
    assert get_execution_cost("ESCALATE") == 12.00
    assert get_execution_cost("STOP") == 0.00


def test_compute_recovery_impact_metrics():
    """Test calculation of top-level Incremental ROI metrics and breakdowns."""
    res = compute_recovery_impact_metrics()
    assert "metrics" in res
    assert "interventions" in res
    assert "event_types" in res

    m = res["metrics"]
    assert m["total_revenue_at_risk"] > 0
    assert m["total_recovered"] > 0
    assert m["estimated_baseline_recovery"] > 0
    assert m["estimated_incremental_recovery"] >= 0
    assert m["net_incremental_value"] >= 0
    assert m["estimated_roi"] >= 0.0

    # Verify mathematical relationship: Net Value = Incremental - Execution Cost
    expected_net = max(0.0, round(m["estimated_incremental_recovery"] - m["execution_cost"], 2))
    assert abs(m["net_incremental_value"] - expected_net) < 1.0


def test_transaction_attribution_trace():
    """Test transaction-level attribution for a single case."""
    # Query case ID from API first
    cases_res = client.get("/cases?page=1&limit=1")
    assert cases_res.status_code == 200
    event_id = cases_res.json()["cases"][0]["event_id"]

    attr_res = client.get(f"/cases/{event_id}/attribution")
    assert attr_res.status_code == 200
    data = attr_res.json()

    assert data["event_id"] == event_id
    assert "amount_at_risk" in data
    assert "baseline_probability" in data
    assert "estimated_baseline_recovery" in data
    assert "estimated_incremental_recovery" in data
    assert "execution_cost" in data
    assert "net_incremental_value" in data


def test_analytics_api_endpoints():
    """Test REST API endpoints /analytics/recovery-impact, /analytics/interventions, /analytics/event-types."""
    res1 = client.get("/analytics/recovery-impact")
    assert res1.status_code == 200
    assert "metrics" in res1.json()

    res2 = client.get("/analytics/interventions")
    assert res2.status_code == 200
    assert "interventions" in res2.json()

    res3 = client.get("/analytics/event-types")
    assert res3.status_code == 200
    assert "event_types" in res3.json()


def test_copilot_incremental_roi_query():
    """Test Copilot answering incremental recovery & ROI questions authoritatively."""
    res = client.post(
        "/copilot/query",
        json={"query": "How much incremental revenue did RecoverAI generate?"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "incremental recovery" in data["answer"].lower()
    assert "roi" in data["answer"].lower()
    assert "attribution_summary" in data
