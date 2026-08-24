"""
Event Schema for RecoverAI - Payment Recovery Data Foundation (Phase 1).

Defines the Pydantic data models for revenue events, historical customer metadata,
and ground-truth labels used in model training, policy evaluation, and audit logging.
"""

from datetime import datetime
from typing import Dict, Literal, Optional, Any
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator


EventType = Literal[
    "payment_failure",
    "checkout_abandonment",
    "subscription_failure",
    "overdue_invoice",
]

FailureReason = Literal[
    "insufficient_funds",
    "card_declined",
    "network_error",
    "expired_card",
    "abandoned",
    "overdue",
]


class CustomerHistorySummary(BaseModel):
    """
    Summary of customer's historical payment performance.
    """
    total_past_payments: int = Field(
        ..., ge=0, description="Total historical payment attempts by this customer"
    )
    past_successful_payments: int = Field(
        ..., ge=0, description="Total successful historical payments"
    )
    past_recovery_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Historical recovery rate (0.0 - 1.0)"
    )

    @field_validator("past_successful_payments")
    @classmethod
    def validate_successful_lte_total(cls, v: int, info) -> int:
        total = info.data.get("total_past_payments", 0)
        if v > total:
            raise ValueError("past_successful_payments cannot exceed total_past_payments")
        return v


class RevenueEvent(BaseModel):
    """
    Core data structure representing a payment or transaction recovery event.
    
    Contains input features, ground truth target labels (hidden at prediction time),
    and placeholder fields to be populated in downstream pipeline phases (Phases 2-4).
    """

    # --- Core Identifiers & Metadata ---
    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique UUID string for the event"
    )
    event_type: EventType = Field(
        ..., description="Type of revenue event (payment_failure, checkout_abandonment, etc.)"
    )
    timestamp: datetime = Field(
        ..., description="ISO timestamp when the event occurred"
    )
    amount: float = Field(
        ..., gt=0.0, description="Transaction amount in INR"
    )
    customer_id: str = Field(
        ..., description="Unique customer identifier"
    )
    failure_reason: Optional[str] = Field(
        None, description="Reason for failure e.g. insufficient_funds, card_declined, abandoned"
    )
    attempt_count: int = Field(
        ..., ge=1, description="Number of recovery/payment attempts so far for this invoice/checkout"
    )
    days_since_last_attempt: float = Field(
        ..., ge=0.0, description="Elapsed time in days since the previous attempt"
    )
    customer_history_summary: CustomerHistorySummary = Field(
        ..., description="Summary metrics of customer's past payment behavior"
    )

    # --- GROUND TRUTH & INTERNAL FIELDS (GROUND-TRUTH-ONLY) ---
    # WARNING: The fields below are ground-truth markers used strictly for data generator validation,
    # training labels, and synthetic evaluation. MUST BE STRIPPED before passing event to LLM Agent.
    archetype: str = Field(
        ...,
        description="INTERNAL GROUND-TRUTH ONLY: Customer archetype that generated this event. DO NOT expose to agent."
    )
    did_recover: bool = Field(
        ...,
        description="GROUND TRUTH LABEL: Whether payment was eventually recovered. Hidden from model at prediction time."
    )

    # --- Pipeline Expansion Fields (Filled in downstream Phases 2-4) ---
    recovery_probability: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Phase 2: ML model predicted recovery probability"
    )
    recommended_action: Optional[str] = Field(
        None, description="Phase 3: LLM agent recommended recovery action"
    )
    policy_decision: Optional[str] = Field(
        None, description="Phase 3: Policy engine approved action or override"
    )
    executed_action: Optional[str] = Field(
        None, description="Phase 4: Action dispatched to payment gateway or communication channel"
    )
    outcome: Optional[str] = Field(
        None, description="Phase 4: Final status e.g. recovered, failed, escalated"
    )
    revenue_recovered: Optional[float] = Field(
        None, ge=0.0, description="Phase 4: Actual revenue recovered in INR"
    )
    reasoning_text: Optional[str] = Field(
        None, description="Phase 3: LLM agent natural language explanation"
    )

    def to_agent_dict(self) -> Dict[str, Any]:
        """
        Returns a dictionary representation safe for LLM agent prompt context or prediction time,
        explicitly removing ground-truth labels (archetype and did_recover).
        """
        data = self.model_dump(mode="json")
        # Strip ground-truth fields to prevent target leakage
        data.pop("archetype", None)
        data.pop("did_recover", None)
        return data
