"""
Webhook Security & Signature Verification for Razorpay Ingestion.
"""

import hmac
import hashlib
import os
from typing import Optional


DEFAULT_TEST_WEBHOOK_SECRET = "rzp_test_secret_recoverai"


def get_webhook_secret() -> str:
    """
    Retrieves Razorpay Webhook Secret from environment variable RAZORPAY_WEBHOOK_SECRET
    or falls back to default test secret for development/testing.
    """
    return os.getenv("RAZORPAY_WEBHOOK_SECRET", DEFAULT_TEST_WEBHOOK_SECRET)


def verify_razorpay_signature(
    raw_body: bytes,
    signature: Optional[str],
    secret: Optional[str] = None
) -> bool:
    """
    Verifies incoming X-Razorpay-Signature HMAC SHA256 signature against raw request body.

    Args:
        raw_body: Raw binary payload bytes of HTTP request.
        signature: Received X-Razorpay-Signature header string.
        secret: Optional explicit webhook secret (defaults to env var or test secret).

    Returns:
        True if signature matches, False otherwise.
    """
    if not signature:
        return False

    webhook_secret = secret or get_webhook_secret()
    
    # Compute HMAC-SHA256 signature
    expected_signature = hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature.lower(), signature.strip().lower())
