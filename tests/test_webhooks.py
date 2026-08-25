"""
Unit tests for Webhook Ingestion, HMAC Signature Verification, and Event Processing.
"""

import json
import hmac
import hashlib
from uuid import uuid4
from fastapi.testclient import TestClient

from backend.api import app
from ingestion.security import verify_razorpay_signature, DEFAULT_TEST_WEBHOOK_SECRET
from ingestion.normalizer import normalize_razorpay_payload
from schema.webhook_schema import NormalizedWebhookEvent

client = TestClient(app)


def test_signature_verification():
    """Test HMAC SHA256 signature verification helper."""
    raw_body = b'{"event":"payment.failed"}'

    # Valid signature calculation
    valid_sig = hmac.new(
        key=DEFAULT_TEST_WEBHOOK_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    assert verify_razorpay_signature(raw_body, valid_sig, secret=DEFAULT_TEST_WEBHOOK_SECRET) is True
    assert verify_razorpay_signature(raw_body, "invalid_signature", secret=DEFAULT_TEST_WEBHOOK_SECRET) is False
    assert verify_razorpay_signature(raw_body, None, secret=DEFAULT_TEST_WEBHOOK_SECRET) is False


def test_event_normalization():
    """Test mapping raw Razorpay payload to NormalizedWebhookEvent schema."""
    raw_payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_9921",
                    "amount": 2500000,
                    "currency": "INR",
                    "customer_id": "cust_test_101",
                    "order_id": "order_test_901",
                    "created_at": 1776543200
                }
            }
        }
    }

    normalized = normalize_razorpay_payload(raw_payload)
    assert isinstance(normalized, NormalizedWebhookEvent)
    assert normalized.source == "razorpay"
    assert normalized.source_event == "payment.failed"
    assert normalized.event_type == "PAYMENT_FAILED"
    assert normalized.payment_id == "pay_test_9921"
    assert normalized.amount == 25000.0  # Converted from paise
    assert normalized.customer_reference == "cust_test_101"


def test_webhook_endpoint_signature_validation():
    """Test POST /webhooks/razorpay rejects invalid signature and accepts valid signature."""
    uid = uuid4().hex[:6]
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_val_{uid}",
                    "amount": 1500000,
                    "currency": "INR",
                    "customer_id": f"cust_val_{uid}"
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
    assert data["processing"]["status"] in ["PROCESSED", "DUPLICATE"]


def test_dev_simulate_webhook():
    """Test POST /dev/webhooks/razorpay/simulate endpoint for payment.failed."""
    uid = uuid4().hex[:6]
    res = client.post(
        "/dev/webhooks/razorpay/simulate",
        json={
            "event_type": "payment.failed",
            "amount": 85000.0,
            "customer_id": f"cust_sim_{uid}",
            "payment_id": f"pay_sim_{uid}"
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "processing_result" in data
    assert data["processing_result"]["status"] in ["PROCESSED", "DUPLICATE"]


def test_webhook_events_log_endpoint():
    """Test GET /webhooks/events log listing endpoint."""
    res = client.get("/webhooks/events")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert "count" in data


def test_unsupported_event_graceful_ignore():
    """Test unsupported event (e.g. refund.created) is stored with IGNORED status."""
    uid = uuid4().hex[:6]
    payload = {
        "event": "refund.created",
        "payload": {
            "refund": {
                "entity": {
                    "id": f"rfnd_{uid}",
                    "amount": 500000,
                    "currency": "INR"
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
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
