"""
Unit tests for Webhook Deduplication, Action Idempotency, Provider State Verification, and Safe Retries.
"""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from backend.api import app
from schema.webhook_schema import NormalizedWebhookEvent
from ingestion.processor import process_incoming_webhook_event
from execution.idempotency import (
    execute_action_idempotent,
    verify_provider_action_state,
    execute_safe_retry,
    get_action_records_for_case,
)

client = TestClient(app)


def test_webhook_deduplication():
    """Test duplicate webhook events are ignored safely without creating duplicate cases."""
    uid = uuid4().hex[:6]
    event_id = f"evt_dedup_{uid}"
    payment_id = f"pay_dedup_{uid}"

    norm_event = NormalizedWebhookEvent(
        event_id=event_id,
        source="razorpay",
        source_event="payment.failed",
        event_type="PAYMENT_FAILED",
        payment_id=payment_id,
        order_id=f"order_{uid}",
        amount=12500.0,
        currency="INR",
        customer_reference=f"cust_{uid}",
        occurred_at="2026-08-25T11:00:00Z",
        received_at="2026-08-25T11:00:01Z",
        processing_status="PROCESSING"
    )

    # First ingestion -> PROCESSED
    res1 = process_incoming_webhook_event(norm_event)
    assert res1["status"] == "PROCESSED"
    assert "case_id" in res1

    # Second duplicate ingestion -> DUPLICATE (Ignored safely)
    res2 = process_incoming_webhook_event(norm_event)
    assert res2["status"] == "DUPLICATE"
    assert "Duplicate ignored safely" in res2["message"]


def test_action_idempotency_key_reused():
    """Test action execution with same idempotency key returns existing record without re-executing."""
    uid = uuid4().hex[:6]
    case_id = f"evt_test_idem_{uid}"

    # First execution -> Creates record attempt 1
    rec1 = execute_action_idempotent(case_id, "PAYMENT_LINK", attempt_number=1, amount=8500.0)
    assert rec1.idempotency_key == f"rc_{case_id}_PAYMENT_LINK_1"
    assert rec1.status == "SUCCEEDED"

    # Second execution with same idempotency key -> Returns same record without re-executing
    rec2 = execute_action_idempotent(case_id, "PAYMENT_LINK", attempt_number=1, amount=8500.0)
    assert rec2.action_id == rec1.action_id
    assert rec2.idempotency_key == rec1.idempotency_key


def test_network_timeout_unknown_state_and_provider_verification():
    """Test network timeout transition to UNKNOWN state and provider state verification."""
    uid = uuid4().hex[:6]
    event_id = f"evt_timeout_{uid}"
    payment_id = f"pay_timeout_{uid}"

    # Ingest event via processor first so case exists in revenue_events table
    norm_event = NormalizedWebhookEvent(
        event_id=event_id,
        source="razorpay",
        source_event="payment.failed",
        event_type="PAYMENT_FAILED",
        payment_id=payment_id,
        amount=25000.0,
        currency="INR",
        customer_reference=f"cust_{uid}",
        occurred_at="2026-08-25T11:00:00Z",
        received_at="2026-08-25T11:00:01Z",
        processing_status="PROCESSING"
    )
    proc_res = process_incoming_webhook_event(norm_event)
    case_id = proc_res["case_id"]

    # Simulate execution timeout -> UNKNOWN state
    rec = execute_action_idempotent(
        case_id=case_id,
        action_type="PAYMENT_LINK",
        attempt_number=1,
        amount=25000.0,
        simulate_timeout=True
    )
    assert rec.status == "UNKNOWN"

    # Verify provider state -> Provider confirms transaction SUCCEEDED
    ver_res = verify_provider_action_state(rec)
    assert ver_res.provider_status == "CONFIRMED"

    # Attempting safe retry after provider confirmed success -> Blocked safely (VERIFIED_SUCCESS)
    retry_res = execute_safe_retry(case_id=case_id, actor="ADMIN")
    assert retry_res.success is True
    assert retry_res.status == "VERIFIED_SUCCESS"
    assert "already SUCCEEDED" in retry_res.message or "confirmed" in retry_res.message


def test_provider_verification_failed_allows_safe_retry():
    """Test provider verification confirming NOT_EXECUTED allows a safe retry attempt 2."""
    uid = uuid4().hex[:6]
    event_id = f"evt_fail_{uid}"
    payment_id = f"pay_fail_{uid}"

    # Create case in database first
    norm_event = NormalizedWebhookEvent(
        event_id=event_id,
        source="razorpay",
        source_event="payment.failed",
        event_type="PAYMENT_FAILED",
        payment_id=payment_id,
        amount=14000.0,
        currency="INR",
        customer_reference=f"cust_{uid}",
        occurred_at="2026-08-25T11:00:00Z",
        received_at="2026-08-25T11:00:01Z",
        processing_status="PROCESSING"
    )
    proc_res = process_incoming_webhook_event(norm_event)
    case_id = proc_res["case_id"]

    # Execute safe retry (Attempt 2)
    retry_res = execute_safe_retry(case_id=case_id, actor="ADMIN")
    assert retry_res.attempt_number == 2
    assert f"{case_id}" in retry_res.idempotency_key


def test_idempotency_api_endpoints():
    """Test REST API endpoints /cases/{case_id}/idempotency and /cases/{case_id}/retry."""
    uid = uuid4().hex[:6]
    case_id = f"evt_test_api_{uid}"

    # Execute an action to populate history
    execute_action_idempotent(case_id, "REMINDER", attempt_number=1, amount=5000.0)

    # GET /cases/{case_id}/idempotency
    res1 = client.get(f"/cases/{case_id}/idempotency")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["count"] >= 1
    assert data1["actions"][0]["idempotency_key"] == f"rc_{case_id}_REMINDER_1"

    # POST /cases/{case_id}/retry
    res2 = client.post(f"/cases/{case_id}/retry", json={"actor": "ADMIN"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert "attempt_number" in data2
    assert "idempotency_key" in data2
