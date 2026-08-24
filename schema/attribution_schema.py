"""
Pydantic Schemas for Incremental ROI Attribution, Recovery Intelligence, and Experiments.
"""

from datetime import datetime
from typing import Optional, Literal, Dict, Any, List
from pydantic import BaseModel, Field


ConfidenceLevel = Literal["HIGH", "MEDIUM", "EARLY_SIGNAL"]


class AttributionMetrics(BaseModel):
    """Top-level Incremental ROI & Financial Impact Metrics."""
    total_revenue_at_risk: float = Field(..., description="Total revenue at risk in INR")
    total_recovered: float = Field(..., description="Total observed recovered revenue in INR")
    estimated_baseline_recovery: float = Field(..., description="Estimated organic baseline recovery in INR")
    estimated_incremental_recovery: float = Field(..., description="Estimated incremental revenue lift in INR")
    recovery_lift_percent: float = Field(..., description="Percentage lift vs baseline recovery")
    execution_cost: float = Field(..., description="Estimated execution cost in INR")
    net_incremental_value: float = Field(..., description="Net incremental value (Incremental - Execution Cost) in INR")
    estimated_roi: float = Field(..., description="Estimated ROI multiplier e.g. 80.3x")


class InterventionPerformance(BaseModel):
    """Performance & Incremental Impact Breakdown per Intervention Type."""
    action: str = Field(..., description="Intervention action name e.g. PAYMENT_LINK")
    cases: int = Field(..., description="Case count")
    recovered: float = Field(..., description="Observed recovered revenue in INR")
    estimated_baseline: float = Field(..., description="Estimated organic baseline recovery in INR")
    estimated_incremental: float = Field(..., description="Estimated incremental recovery in INR")
    lift_percent: float = Field(..., description="Percentage lift vs baseline")
    observed_rate: float = Field(..., description="Observed recovery rate %")
    baseline_rate: float = Field(..., description="Estimated organic baseline rate %")
    sample_size: int = Field(..., description="Sample size of cases evaluated")
    confidence: ConfidenceLevel = Field("HIGH", description="Confidence level based on sample size")


class EventTypePerformance(BaseModel):
    """Performance Breakdown per Leakage Category / Event Type."""
    event_type: str = Field(..., description="Event type identifier e.g. payment_failure")
    label: str = Field(..., description="Display label e.g. PAYMENT FAILURE")
    cases: int = Field(..., description="Total case count")
    revenue_at_risk: float = Field(..., description="Revenue at risk in INR")
    recovered: float = Field(..., description="Observed recovered revenue in INR")
    estimated_baseline: float = Field(..., description="Estimated organic baseline recovery in INR")
    estimated_incremental: float = Field(..., description="Estimated incremental recovery in INR")
    recovery_rate: float = Field(..., description="Observed recovery rate %")


class CaseAttributionTrace(BaseModel):
    """Transaction-level attribution trace for individual recovered cases."""
    event_id: str = Field(..., description="Case ID")
    customer_id: str = Field(..., description="Customer ID")
    amount_at_risk: float = Field(..., description="Amount at risk in INR")
    observed_recovery: float = Field(..., description="Observed recovered revenue in INR")
    baseline_probability: float = Field(..., description="Organic baseline recovery probability")
    estimated_baseline_recovery: float = Field(..., description="Estimated baseline recovery in INR")
    estimated_incremental_recovery: float = Field(..., description="Estimated incremental recovery in INR")
    intervention: str = Field(..., description="Executed intervention")
    execution_cost: float = Field(..., description="Intervention execution cost in INR")
    net_incremental_value: float = Field(..., description="Net incremental value in INR")
    recoverai_probability: float = Field(..., description="ML predicted recovery probability")
    policy_version: str = Field("policy_v2_2026", description="Policy version used")


class ExperimentCreateRequest(BaseModel):
    """Payload for POST /experiments."""
    name: str = Field(..., description="Experiment name e.g. Failed Card Recovery v1")
    event_type: str = Field("payment_failure", description="Target event type")
    segment: str = Field("CARD", description="Customer segment identifier")
    control_strategy: str = Field("RETRY_AFTER_24H", description="Control group strategy")
    treatment_strategy: str = Field("PAYMENT_LINK_AFTER_30M", description="Treatment group strategy")
    traffic_allocation: str = Field("50/50", description="Traffic split e.g. 50/50")


class ExperimentRecord(BaseModel):
    """Experiment record with calculated control vs treatment lift."""
    experiment_id: str = Field(..., description="Experiment UUID")
    name: str = Field(..., description="Experiment name")
    event_type: str = Field(..., description="Target event type")
    segment: str = Field(..., description="Target segment")
    control_strategy: str = Field(..., description="Control strategy")
    treatment_strategy: str = Field(..., description="Treatment strategy")
    traffic_allocation: str = Field("50/50", description="Allocation ratio")
    control_cases: int = Field(..., description="Control group sample count")
    treatment_cases: int = Field(..., description="Treatment group sample count")
    control_recovery_rate: float = Field(..., description="Control recovery rate %")
    treatment_recovery_rate: float = Field(..., description="Treatment recovery rate %")
    absolute_lift: float = Field(..., description="Absolute lift in percentage points (+pp)")
    relative_lift: float = Field(..., description="Relative lift %")
    estimated_incremental_revenue: float = Field(..., description="Incremental revenue generated in INR")
    confidence: ConfidenceLevel = Field(..., description="Confidence level")
    created_at: str = Field(..., description="ISO timestamp")
