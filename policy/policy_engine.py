"""
Deterministic Policy Engine for RecoverAI (Phase 3).

Evaluates LLM agent recommendations against hard operational guardrails defined in policy/rules.yaml.
Returns a PolicyEvaluationResult indicating approval status, blocking rule (if any),
and a safe fallback final_action. 100% deterministic Python logic with zero AI dependencies.
"""

import os
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field
import yaml

from schema.event_schema import RevenueEvent


class PolicyEvaluationResult(BaseModel):
    """Result returned by the deterministic policy evaluation engine."""
    approved: bool = Field(
        ..., description="True if recommended action passes all policy guardrails, False if blocked."
    )
    final_action: str = Field(
        ..., description="Approved action or safe rule-derived fallback action (never the blocked LLM action)."
    )
    blocking_rule: Optional[str] = Field(
        None, description="Name of the specific policy rule that blocked the recommendation (None if approved)."
    )


def load_policy_rules(yaml_path: str = "policy/rules.yaml") -> Dict[str, Any]:
    """Loads policy rule configurations from YAML file."""
    if not os.path.exists(yaml_path):
        # Default rules matching Phase 1 specification
        return {
            "max_retry_attempts": 3,
            "retry_cooldown_minutes": 30,
            "escalation_after_failed_attempts": 4,
            "payment_link_threshold_amount": 20000,
            "stop_if_recovery_probability_below": 0.20,
            "max_daily_contact_attempts_per_customer": 2,
        }
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def evaluate_policy(
    event: RevenueEvent,
    recommended_action: str,
    rules: Optional[Dict[str, Any]] = None
) -> PolicyEvaluationResult:
    """
    Evaluates a recommended recovery action against policy guardrails.

    Args:
        event: RevenueEvent instance containing transaction & customer features.
        recommended_action: Action recommended by the LLM agent (RETRY, PAYMENT_LINK, REMINDER, ESCALATE, STOP).
        rules: Optional dict of policy rules. If None, loads from policy/rules.yaml.

    Returns:
        PolicyEvaluationResult: Structured evaluation with approved flag, final_action, and blocking_rule.
    """
    if rules is None:
        rules = load_policy_rules()

    rec_action = recommended_action.upper().strip()

    # Rule 1: stop_if_recovery_probability_below (e.g. 0.20)
    # Unit economics guardrail: Stop recovery if ML probability < 20%
    stop_prob_thresh = float(rules.get("stop_if_recovery_probability_below", 0.20))
    if event.recovery_probability is not None and event.recovery_probability < stop_prob_thresh:
        if rec_action != "STOP":
            return PolicyEvaluationResult(
                approved=False,
                final_action="STOP",
                blocking_rule="stop_if_recovery_probability_below"
            )

    # Rule 2: payment_link_threshold_amount (e.g. ₹20,000 INR)
    # RBI 2FA mandate: High-value transactions cannot use automated retry, must use payment link
    link_amount_thresh = float(rules.get("payment_link_threshold_amount", 20000))
    if event.amount >= link_amount_thresh:
        if rec_action == "RETRY":
            return PolicyEvaluationResult(
                approved=False,
                final_action="PAYMENT_LINK",
                blocking_rule="payment_link_threshold_amount"
            )

    # Rule 3: max_retry_attempts (e.g. 3 attempts)
    # Visa/Mastercard network retry cap: Block automated retry if attempt_count >= 3
    max_retries = int(rules.get("max_retry_attempts", 3))
    if rec_action == "RETRY" and event.attempt_count >= max_retries:
        return PolicyEvaluationResult(
            approved=False,
            final_action="ESCALATE",
            blocking_rule="max_retry_attempts"
        )

    # Rule 4: retry_cooldown_minutes (e.g. 30 minutes = 0.0208 days)
    # Bank velocity filter: Require minimum cooldown period between retries
    cooldown_minutes = float(rules.get("retry_cooldown_minutes", 30))
    cooldown_days = cooldown_minutes / 1440.0
    if rec_action == "RETRY" and event.days_since_last_attempt < cooldown_days:
        return PolicyEvaluationResult(
            approved=False,
            final_action="STOP",
            blocking_rule="retry_cooldown_minutes"
        )

    # Rule 5: escalation_after_failed_attempts (e.g. 4 attempts)
    # Diminishing returns guardrail: Escalate to human support if 4 or more attempts have failed
    escalate_thresh = int(rules.get("escalation_after_failed_attempts", 4))
    if event.attempt_count >= escalate_thresh and rec_action in ["RETRY", "REMINDER"]:
        return PolicyEvaluationResult(
            approved=False,
            final_action="ESCALATE",
            blocking_rule="escalation_after_failed_attempts"
        )

    # Rule 6: max_daily_contact_attempts_per_customer (e.g. 2 attempts per day)
    # TRAI anti-spam compliance: Prevent excessive customer communications within 24 hours
    max_daily_contacts = int(rules.get("max_daily_contact_attempts_per_customer", 2))
    if rec_action == "REMINDER" and event.days_since_last_attempt < 1.0 and event.attempt_count >= max_daily_contacts:
        return PolicyEvaluationResult(
            approved=False,
            final_action="STOP",
            blocking_rule="max_daily_contact_attempts_per_customer"
        )

    # If all guardrails pass, approve recommendation unchanged
    return PolicyEvaluationResult(
        approved=True,
        final_action=rec_action,
        blocking_rule=None
    )
