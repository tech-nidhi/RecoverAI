"""
Pydantic Schemas for Razorpay Webhook Ingestion and Normalization.
"""

from datetime import datetime
from typing import Optional, Literal, Dict, Any
from uuid import uuid4
from pydantic import BaseModel, Field

ProcessingStatus = Literal["RECEIVED", "PROCESSING", "PROCESSED", "FAILED", "IGNORED"]

NormalizedEventType = Literal[
    "PAYMENT_FAILED",
    "PAYMENT_AUTHORIZED",
    "PAYMENT_CAPTURED",
    "ORDER_PAID",
    "PAYMENT_LINK_PAID",
    "UNSUPPORTED"
]


class NormalizedWebhookEvent(BaseModel):
    """
    Internal normalized event model representing a payment lifecycle event
    ingested from Razorpay or external gateways.
    """
    event_id: str = Field(
        default_factory=lambda: f"evt_rzp_{uuid4().hex[:12]}",
        description="Unique internal event identifier"
    )
    source: str = Field("razorpay", description="Webhook source provider")
    source_event: str = Field(..., description="Original Razorpay event name e.g. payment.failed")
    event_type: NormalizedEventType = Field(..., description="Internal normalized event type")
    payment_id: Optional[str] = Field(None, description="Razorpay payment ID (pay_xxx)")
    order_id: Optional[str] = Field(None, description="Razorpay order ID (order_xxx)")
    amount: float = Field(..., gt=0.0, description="Amount in INR")
    currency: str = Field("INR", description="Currency code")
    customer_reference: str = Field(..., description="Customer ID, email, or account reference")
    occurred_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO timestamp when event occurred at source"
    )
    received_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO timestamp when event was ingested by RecoverAI"
    )
    processing_status: ProcessingStatus = Field("RECEIVED", description="Current processing status")
    error_message: Optional[str] = Field(None, description="Processing error or ignore reason")


class WebhookSimulationRequest(BaseModel):
    """
    Payload for development/test endpoint /dev/webhooks/razorpay/simulate.
    """
    event_type: Literal[
        "payment.failed",
        "payment.authorized",
        "payment.captured",
        "order.paid",
        "payment_link.paid"
    ] = Field("payment.failed", description="Razorpay event type to simulate")
    amount: float = Field(1249.00, gt=0.0, description="Transaction amount in INR")
    customer_id: str = Field("cust_test_9981", description="Customer reference ID")
    payment_id: Optional[str] = Field(None, description="Optional payment ID")
    failure_reason: Optional[str] = Field("INSUFFICIENT_FUNDS", description="Failure reason if payment.failed")
