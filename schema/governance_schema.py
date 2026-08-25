"""
Pydantic Schemas for Policy Governance, Human Approval, and Kill Switch Controls.
"""

from datetime import datetime
from typing import Optional, Literal, Dict, Any, List
from pydantic import BaseModel, Field


GovernanceDecisionType = Literal["ALLOW", "BLOCK", "APPROVAL_REQUIRED"]
ApprovalStatus = Literal["PENDING_APPROVAL", "AUTHORIZED", "HUMAN_REJECTED", "APPROVAL_EXPIRED"]


class GovernancePolicyConfig(BaseModel):
    """Configuration model for RecoverAI Governance Layer."""
    global_automation_active: bool = Field(True, description="Global Kill Switch state")
    policy_version: str = Field("policy_v2_2026", description="Active policy version identifier")
    max_retries: int = Field(3, ge=1, le=10, description="Max allowed payment retry attempts")
    retry_cooldown_hours: float = Field(24.0, ge=0.0, description="Cooldown period in hours between retries")
    max_daily_auto_exposure: float = Field(100000000.0, gt=0.0, description="Max daily automated recovery exposure cap in INR")
    max_customer_interventions: int = Field(3, ge=1, description="Max automated interventions per customer")
    human_approval_threshold: float = Field(100000.0, gt=0.0, description="Transaction amount threshold requiring human approval")
    action_controls: Dict[str, bool] = Field(
        default_factory=lambda: {
            "RETRY": True,
            "PAYMENT_LINK": True,
            "REMINDER": True,
            "ESCALATE": True
        },
        description="Per-action automation toggles"
    )


class PolicyDecision(BaseModel):
    """Structured policy decision object produced for every recovery action evaluation."""
    decision: GovernanceDecisionType = Field(..., description="ALLOW, BLOCK, or APPROVAL_REQUIRED")
    action: str = Field(..., description="Target recovery action e.g. PAYMENT_LINK")
    policy_version: str = Field(..., description="Policy version used for decision")
    kill_switch_active: bool = Field(..., description="True if automation active, False if kill switch engaged")
    action_enabled: bool = Field(True, description="Action-level toggle state")
    amount_allowed: bool = Field(True, description="Whether transaction amount passes threshold checks")
    cooldown_satisfied: bool = Field(True, description="Whether cooldown period is satisfied")
    retry_limit_satisfied: bool = Field(True, description="Whether retry attempt limit is satisfied")
    customer_limit_satisfied: bool = Field(True, description="Whether per-customer intervention cap is satisfied")
    exposure_limit_satisfied: bool = Field(True, description="Whether daily exposure cap is satisfied")
    human_approval_required: bool = Field(False, description="True if transaction requires manual human authorization")
    rejection_reason: Optional[str] = Field(None, description="Reason code if decision is BLOCK")
    approval_id: Optional[str] = Field(None, description="Approval request ID if decision is APPROVAL_REQUIRED")


class KillSwitchToggleRequest(BaseModel):
    """Payload for POST /governance/kill-switch."""
    active: bool = Field(..., description="True to activate automation, False to engage Kill Switch")
    actor: str = Field("ADMIN", description="Identity of admin making change")
    reason: Optional[str] = Field("Manual safety intervention", description="Reason for toggle")


class ActionControlToggleRequest(BaseModel):
    """Payload for POST /governance/action-control."""
    action: str = Field(..., description="Action name e.g. RETRY, PAYMENT_LINK, REMINDER, ESCALATE")
    enabled: bool = Field(..., description="True to enable, False to disable")
    actor: str = Field("ADMIN", description="Identity of admin making change")


class HumanApprovalDecisionRequest(BaseModel):
    """Payload for POST /governance/approvals/{id}/decision."""
    decision: Literal["APPROVE", "REJECT"] = Field(..., description="Approval decision: APPROVE or REJECT")
    actor: str = Field("ADMIN", description="Identity of approving manager")
    notes: Optional[str] = Field(None, description="Optional decision notes")
