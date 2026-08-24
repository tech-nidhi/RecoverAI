"""
Unit tests for Recovery Experiments, Strategy Comparisons, and Lift Calculations.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from analytics.experiments import (
    get_all_experiments,
    create_experiment,
    get_experiment_detail,
)
from schema.attribution_schema import ExperimentCreateRequest

client = TestClient(app)


def test_get_all_experiments():
    """Test retrieving active & completed recovery strategy experiments."""
    res = client.get("/experiments")
    assert res.status_code == 200
    data = res.json()
    assert "experiments" in data
    assert len(data["experiments"]) >= 3

    # Check lift calculations on seeded experiment
    exp = data["experiments"][0]
    assert "absolute_lift" in exp
    assert "relative_lift" in exp
    assert exp["treatment_recovery_rate"] > exp["control_recovery_rate"]


def test_create_new_experiment():
    """Test creating a new control vs treatment recovery experiment via REST API."""
    payload = {
        "name": "UPI Autopay Retry Optimization v3",
        "event_type": "subscription_failure",
        "segment": "UPI_AUTOPAY",
        "control_strategy": "STANDARD_RETRY",
        "treatment_strategy": "DYNAMIC_RETRY_WINDOW",
        "traffic_allocation": "50/50"
    }

    res = client.post("/experiments", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "UPI Autopay Retry Optimization v3"
    assert data["segment"] == "UPI_AUTOPAY"
    assert data["absolute_lift"] > 0
    assert "experiment_id" in data

    # Verify single experiment detail endpoint
    exp_id = data["experiment_id"]
    detail_res = client.get(f"/experiments/{exp_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["experiment_id"] == exp_id
