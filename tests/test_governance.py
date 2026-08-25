"""
Unit tests for Policy Governance Layer, Global Kill Switch, Human Approval Workflow,
and Action Controls.
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from backend.api import app
from policy.governance import (
    evaluate_governance,
    update_governance_config,
    get_governance_config,
    create_approval_request,
    decide_approval_request,
    get_pending_approvals,
    record_governance_audit
)

client = TestClient(app)


def setup_function():
    """Reset governance config before each test."""
    update_governance_config({
        "global_automation_active": True,
        "policy_version": "policy_v2_2026",
        "max_retries": 3,
        "retry_cooldown_hours": 24.0,
        "max_daily_auto_exposure": 100000000.0,
        "max_customer_interventions": 3,
        "human_approval_threshold": 100000.0,
        "action_controls": {
            "RETRY": True,
            "PAYMENT_LINK": True,
            "REMINDER": True,
            "ESCALATE": True
        }
    }, actor="TEST_SETUP")


def test_kill_switch_active_vs_paused():
    """Test Global Kill Switch blocks actions when paused and allows when active."""
    case = {"amount": 25000.0, "customer_id": "cust_kill_101", "attempt_count": 1, "days_since_last_attempt": 2.0}

    # 1. Active -> ALLOW
    res_active = evaluate_governance(case, "PAYMENT_LINK")
    assert res_active.decision == "ALLOW"
    assert res_active.kill_switch_active is True

    # 2. Pause Kill Switch -> BLOCK
    update_governance_config({"global_automation_active": False}, actor="ADMIN", reason="Emergency pause test")
    res_paused = evaluate_governance(case, "PAYMENT_LINK")
    assert res_paused.decision == "BLOCK"
    assert res_paused.rejection_reason == "GLOBAL_AUTOMATION_PAUSED"
    assert res_paused.kill_switch_active is False


def test_action_level_controls():
    """Test individual action toggles block disabled actions."""
    case = {"amount": 15000.0, "customer_id": "cust_action_101", "attempt_count": 1, "days_since_last_attempt": 2.0}

    # Disable REMINDER action
    update_governance_config({
        "action_controls": {"RETRY": True, "PAYMENT_LINK": True, "REMINDER": False, "ESCALATE": True}
    }, actor="ADMIN")

    res_link = evaluate_governance(case, "PAYMENT_LINK")
    assert res_link.decision == "ALLOW"

    res_rem = evaluate_governance(case, "REMINDER")
    assert res_rem.decision == "BLOCK"
    assert res_rem.rejection_reason == "ACTION_AUTOMATION_DISABLED"


def test_max_retry_limit():
    """Test max retry limit caps automated retries."""
    case_attempt_2 = {"amount": 12000.0, "attempt_count": 2, "days_since_last_attempt": 2.0}
    case_attempt_3 = {"amount": 12000.0, "attempt_count": 3, "days_since_last_attempt": 2.0}

    assert evaluate_governance(case_attempt_2, "RETRY").decision == "ALLOW"
    
    res_cap = evaluate_governance(case_attempt_3, "RETRY")
    assert res_cap.decision == "BLOCK"
    assert res_cap.rejection_reason == "MAX_RETRY_LIMIT_REACHED"


def test_retry_cooldown_window():
    """Test cooldown window prevents back-to-back retries."""
    case_cooldown_active = {"amount": 12000.0, "attempt_count": 1, "days_since_last_attempt": 0.2}  # ~4.8 hours
    case_cooldown_passed = {"amount": 12000.0, "attempt_count": 1, "days_since_last_attempt": 1.2}  # 28.8 hours

    res_blocked = evaluate_governance(case_cooldown_active, "RETRY")
    assert res_blocked.decision == "BLOCK"
    assert res_blocked.rejection_reason == "COOLDOWN_ACTIVE"

    res_passed = evaluate_governance(case_cooldown_passed, "RETRY")
    assert res_passed.decision == "ALLOW"


def test_human_approval_threshold_and_decision():
    """Test amounts > ₹1,00,000 require human approval and decision API works."""
    case_low = {"event_id": "evt_low_50k", "amount": 50000.0, "customer_id": "cust_50k", "attempt_count": 1, "days_since_last_attempt": 2.0}
    case_high = {"event_id": "evt_high_245k", "amount": 245033.0, "customer_id": "cust_245k", "attempt_count": 1, "days_since_last_attempt": 2.0}

    # Low amount -> ALLOW
    res_low = evaluate_governance(case_low, "PAYMENT_LINK")
    assert res_low.decision == "ALLOW"

    # High amount -> APPROVAL_REQUIRED
    res_high = evaluate_governance(case_high, "PAYMENT_LINK")
    assert res_high.decision == "APPROVAL_REQUIRED"
    assert res_high.approval_id is not None

    appr_id = res_high.approval_id

    # Query pending approvals API
    pending_res = client.get("/governance/approvals")
    assert pending_res.status_code == 200
    pending_list = pending_res.json()["approvals"]
    assert any(a["approval_id"] == appr_id for a in pending_list)

    # Approve request via API -> AUTHORIZED
    dec_res = client.post(
        f"/governance/approvals/{appr_id}/decision",
        json={"decision": "APPROVE", "actor": "SUPER_ADMIN", "notes": "Approved for enterprise client"}
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["status"] == "AUTHORIZED"


def test_human_approval_rejection():
    """Test manual rejection of approval request."""
    case = {"event_id": "evt_rej_180k", "amount": 180000.0, "customer_id": "cust_rej", "attempt_count": 1, "days_since_last_attempt": 2.0}
    res = evaluate_governance(case, "PAYMENT_LINK")
    assert res.decision == "APPROVAL_REQUIRED"
    appr_id = res.approval_id

    dec_res = client.post(
        f"/governance/approvals/{appr_id}/decision",
        json={"decision": "REJECT", "actor": "RISK_OFFICER", "notes": "High fraud probability"}
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["status"] == "HUMAN_REJECTED"


def test_kill_switch_api_endpoints():
    """Test REST API endpoints /governance/kill-switch and /governance/action-control."""
    # 1. GET /governance/config
    cfg_res = client.get("/governance/config")
    assert cfg_res.status_code == 200
    assert cfg_res.json()["global_automation_active"] is True

    # 2. POST /governance/kill-switch (Pause)
    pause_res = client.post("/governance/kill-switch", json={"active": False, "actor": "TEST_ADMIN", "reason": "Emergency safety lock"})
    assert pause_res.status_code == 200
    assert pause_res.json()["global_automation_active"] is False

    # 3. Resume Kill Switch
    resume_res = client.post("/governance/kill-switch", json={"active": True, "actor": "TEST_ADMIN"})
    assert resume_res.status_code == 200
    assert resume_res.json()["global_automation_active"] is True
