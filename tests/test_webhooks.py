"""
Unit tests for Razorpay Webhook Ingestion, Signature Verification, Event Normalization,
Persistence, and Recovery Case Pipeline.
"""

import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient

from backend.api import app
from ingestion.security import verify_razorpay_signature, DEFAULT_TEST_WEBHOOK_SECRET
from ingestion.normalizer import normalize_razorpay_payload
from ingestion.processor import ensure_webhook_tables_exist

client = TestClient(app)


def test_signature_verification():
    """Test HMAC SHA256 signature verification logic."""
    raw_body = b'{"event":"payment.failed","payment_id":"pay_test_1001"}'
    secret = "test_webhook_secret_key"
    
    # Compute correct signature
    valid_sig = hmac.new(key=secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    
    assert verify_razorpay_signature(raw_body, valid_sig, secret=secret) is True
    assert verify_razorpay_signature(raw_body, "invalid_signature_hash", secret=secret) is False
    assert verify_razorpay_signature(raw_body, None, secret=secret) is False


def test_event_normalization():
    """Test Razorpay JSON payload normalization for supported event types."""
    payload_failed = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_failed_123",
                    "amount": 24503300,  # 245,033 INR in paise
                    "currency": "INR",
                    "customer_id": "cust_high_v_4586",
                    "created_at": 1724497200
                }
            }
        }
    }
    
    norm = normalize_razorpay_payload(payload_failed)
    assert norm.source_event == "payment.failed"
    assert norm.event_type == "PAYMENT_FAILED"
    assert norm.payment_id == "pay_failed_123"
    assert norm.amount == 245033.00
    assert norm.currency == "INR"
    assert norm.customer_reference == "cust_high_v_4586"
    assert norm.processing_status == "RECEIVED"


def test_webhook_endpoint_signature_validation():
    """Test POST /webhooks/razorpay rejects invalid signature and accepts valid signature."""
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_valid_8821",
                    "amount": 1500000,
                    "currency": "INR",
                    "customer_id": "cust_valid_101"
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    
    # 1. Invalid signature request -> 400
    res_bad = client.post(
        "/webhooks/razorpay",
        content=body_bytes,
        headers={"X-Razorpay-Signature": "invalid_sig", "Content-Type": "application/json"}
    )
    assert res_bad.status_code == 400
    assert "Invalid or missing" in res_bad.json()["detail"]

    # 2. Valid signature request -> 200 Accepted
    valid_sig = hmac.new(
        key=DEFAULT_TEST_WEBHOOK_SECRET.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    res_good = client.post(
        "/webhooks/razorpay",
        content=body_bytes,
        headers={"X-Razorpay-Signature": valid_sig, "Content-Type": "application/json"}
    )
    assert res_good.status_code == 200
    data = res_good.json()
    assert data["status"] == "accepted"
    assert "evt_rzp_pay_valid_8821" in data["event_id"]
    assert data["processing"]["status"] == "PROCESSED"


def test_dev_simulate_webhook():
    """Test POST /dev/webhooks/razorpay/simulate endpoint for payment.failed."""
    res = client.post(
        "/dev/webhooks/razorpay/simulate",
        json={
            "event_type": "payment.failed",
            "amount": 85000.0,
            "customer_id": "cust_sim_7721",
            "payment_id": "pay_sim_85000"
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["processing_result"]["event_type"] == "PAYMENT_FAILED"
    assert data["processing_result"]["amount"] == 85000.0
    assert "recovery_probability" in data["processing_result"]
    assert "recommended_action" in data["processing_result"]


def test_webhook_events_log_endpoint():
    """Test GET /webhooks/events retrieves stored webhook records."""
    res = client.get("/webhooks/events?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert len(data["events"]) > 0


def test_unsupported_event_graceful_ignore():
    """Test unsupported event (e.g. refund.created) is marked IGNORED without failing."""
    payload_unsupported = {"event": "refund.created", "amount": 500}
    body_bytes = json.dumps(payload_unsupported).encode("utf-8")
    valid_sig = hmac.new(
        key=DEFAULT_TEST_WEBHOOK_SECRET.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    res = client.post(
        "/webhooks/razorpay",
        content=body_bytes,
        headers={"X-Razorpay-Signature": valid_sig, "Content-Type": "application/json"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["processing"]["status"] == "IGNORED"
    assert "ignores unsupported source event" in data["processing"]["message"]
