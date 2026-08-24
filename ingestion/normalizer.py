"""
Razorpay Webhook Payload Normalizer for RecoverAI.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from uuid import uuid4

from schema.webhook_schema import NormalizedWebhookEvent, NormalizedEventType


RAZORPAY_EVENT_MAP: Dict[str, NormalizedEventType] = {
    "payment.failed": "PAYMENT_FAILED",
    "payment.authorized": "PAYMENT_AUTHORIZED",
    "payment.captured": "PAYMENT_CAPTURED",
    "order.paid": "ORDER_PAID",
    "payment_link.paid": "PAYMENT_LINK_PAID",
}


def normalize_razorpay_payload(payload: Dict[str, Any]) -> NormalizedWebhookEvent:
    """
    Transforms raw Razorpay webhook JSON payload into normalized internal NormalizedWebhookEvent.

    Args:
        payload: Dict representing parsed Razorpay webhook payload.

    Returns:
        NormalizedWebhookEvent instance.
    """
    source_event = payload.get("event", "unknown")
    event_type = RAZORPAY_EVENT_MAP.get(source_event, "UNSUPPORTED")

    # Extract entity payload (payment or order or payment_link)
    payload_data = payload.get("payload", {})
    payment_entity = payload_data.get("payment", {}).get("entity", {})
    order_entity = payload_data.get("order", {}).get("entity", {})
    payment_link_entity = payload_data.get("payment_link", {}).get("entity", {})

    # Extract IDs
    payment_id = payment_entity.get("id") or payload.get("payment_id")
    order_id = payment_entity.get("order_id") or order_entity.get("id") or payload.get("order_id")
    
    # Extract Amount (Razorpay delivers amount in paise: 100 paise = 1 INR)
    raw_amount = payment_entity.get("amount") or order_entity.get("amount") or payment_link_entity.get("amount") or payload.get("amount", 10000)
    if isinstance(raw_amount, (int, float)) and raw_amount > 500:
        amount_inr = round(float(raw_amount) / 100.0, 2)
    else:
        amount_inr = float(raw_amount)

    currency = payment_entity.get("currency") or order_entity.get("currency") or "INR"
    
    # Extract Customer Reference
    customer_reference = (
        payment_entity.get("customer_id") or
        payment_entity.get("email") or
        payment_entity.get("contact") or
        payment_link_entity.get("customer", {}).get("email") or
        payload.get("customer_id") or
        f"cust_rzp_{uuid4().hex[:6]}"
    )

    # Extract Created At Timestamp
    created_at_ts = payment_entity.get("created_at") or order_entity.get("created_at") or payload.get("created_at")
    if created_at_ts and isinstance(created_at_ts, (int, float)):
        occurred_at = datetime.utcfromtimestamp(created_at_ts).isoformat() + "Z"
    else:
        occurred_at = datetime.utcnow().isoformat() + "Z"

    event_id = f"evt_rzp_{payment_id or uuid4().hex[:8]}"

    return NormalizedWebhookEvent(
        event_id=event_id,
        source="razorpay",
        source_event=source_event,
        event_type=event_type,
        payment_id=payment_id,
        order_id=order_id,
        amount=amount_inr,
        currency=currency,
        customer_reference=customer_reference,
        occurred_at=occurred_at,
        received_at=datetime.utcnow().isoformat() + "Z",
        processing_status="RECEIVED"
    )
