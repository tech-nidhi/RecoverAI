"""
Pydantic Schemas for Idempotency, Execution State Machine, and Provider Verification.
"""

from datetime import datetime
from typing import Optional, Literal, Dict, Any, List
from pydantic import BaseModel, Field


ExecutionState = Literal[
    "PENDING",
    "AUTHORIZED",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "UNKNOWN",
    "MANUAL_REVIEW"
]

ProviderStatus = Literal[
    "CONFIRMED",
    "NOT_EXECUTED",
    "UNKNOWN"
]


class IdempotentActionRecord(BaseModel):
    """Persistent execution record tracking idempotency keys and state transitions."""
    action_id: str = Field(..., description="Unique internal action ID e.g. act_9f81a7b2")
    idempotency_key: str = Field(..., description="Deterministic key e.g. rc_evt_rzp_pay_102_PAYMENT_LINK_1")
    case_id: str = Field(..., description="Recovery case ID")
    action_type: str = Field(..., description="Action name e.g. PAYMENT_LINK")
    status: ExecutionState = Field("PENDING", description="Execution state machine status")
    attempt_number: int = Field(1, description="Current attempt number")
    started_at: str = Field(..., description="ISO timestamp when execution started")
    completed_at: Optional[str] = Field(None, description="ISO timestamp when execution completed")
    provider_reference: Optional[str] = Field(None, description="Razorpay gateway reference ID e.g. plink_8f91a2")
    provider_status: Optional[ProviderStatus] = Field(None, description="Provider verification status")
    error_message: Optional[str] = Field(None, description="Error message if execution failed or timed out")
    retry_eligible: bool = Field(True, description="Flag indicating if action is safe to retry")


class ProviderVerificationResult(BaseModel):
    """Result returned when verifying action state with payment gateway."""
    provider_status: ProviderStatus = Field(..., description="Gateway state: CONFIRMED, NOT_EXECUTED, UNKNOWN")
    gateway_reference_id: Optional[str] = Field(None, description="Gateway transaction reference")
    message: str = Field(..., description="Verification status explanation")


class SafeRetryRequest(BaseModel):
    """Payload for POST /cases/{case_id}/retry."""
    actor: str = Field("ADMIN", description="Actor initiating the retry e.g. ADMIN or SYSTEM")
    force_override: bool = Field(False, description="Optional manual override flag")
    simulate_timeout: bool = Field(False, description="Dev flag to simulate network timeout")


class SafeRetryResponse(BaseModel):
    """Response returned after processing a safe retry request."""
    success: bool = Field(..., description="True if retry completed or verified successfully")
    case_id: str = Field(..., description="Case ID")
    status: str = Field(..., description="Result status: EXECUTED, VERIFIED_SUCCESS, BLOCKED, MANUAL_REVIEW")
    attempt_number: int = Field(..., description="Attempt number executed")
    idempotency_key: str = Field(..., description="Idempotency key used")
    message: str = Field(..., description="Detailed status message")
    execution_record: Optional[IdempotentActionRecord] = Field(None, description="Action execution record")
