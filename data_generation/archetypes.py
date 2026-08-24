"""
Archetype Definitions for RecoverAI Synthetic Data Generation.

Defines 5 realistic customer behavior archetypes with probabilistic distributions
over event types, failure reasons, transaction amounts, retry histories, and
base recovery probabilities.
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class ArchetypeConfig:
    """
    Configuration specification for a customer behavioral archetype.
    """
    name: str
    description: str
    
    # Categorical distributions (category_name -> weight)
    event_type_distribution: Dict[str, float]
    failure_reason_distribution: Dict[str, float]
    
    # Range parameters (min, max)
    attempt_count_range: Tuple[int, int]
    days_since_last_attempt_range: Tuple[float, float]
    amount_range: Tuple[float, float]
    
    # Customer history distribution parameters (min, max)
    total_past_payments_range: Tuple[int, int]
    past_success_rate_range: Tuple[float, float]
    
    # Ground truth recovery parameters
    base_recovery_probability: float
    
    # Strategic nuances for explanation / policy context
    preferred_recovery_channel: str = "auto_retry"
    nuance_note: str = ""


# -----------------------------------------------------------------------------
# 5 Customer Archetypes Definitions
# -----------------------------------------------------------------------------

RELIABLE_TEMPORARY_GLITCH = ArchetypeConfig(
    name="reliable_temporary_glitch",
    description=(
        "Established customers with stellar payment histories who encounter transient "
        "network glitches or temporary balance deficits. High past success rate, fails rarely, "
        "and recovers seamlessly on automated retry (~85% recovery rate)."
    ),
    event_type_distribution={
        "payment_failure": 0.65,
        "subscription_failure": 0.35,
    },
    failure_reason_distribution={
        "network_error": 0.55,
        "insufficient_funds": 0.35,
        "card_declined": 0.10,
    },
    attempt_count_range=(1, 2),
    days_since_last_attempt_range=(0.1, 2.0),
    amount_range=(500.0, 15000.0),
    total_past_payments_range=(10, 50),
    past_success_rate_range=(0.85, 0.99),
    base_recovery_probability=0.85,
    preferred_recovery_channel="auto_retry",
    nuance_note="High past success rate; retry within 24h resolves >80% of failures."
)


CHRONIC_FAILER = ArchetypeConfig(
    name="chronic_failer",
    description=(
        "Customers with repeated payment failures, expired instruments, or exhausted credit. "
        "High attempt counts, poor history, and rarely recovers even with multiple retries (~10% recovery rate)."
    ),
    event_type_distribution={
        "payment_failure": 0.50,
        "subscription_failure": 0.50,
    },
    failure_reason_distribution={
        "card_declined": 0.45,
        "expired_card": 0.35,
        "insufficient_funds": 0.20,
    },
    attempt_count_range=(3, 6),
    days_since_last_attempt_range=(1.0, 7.0),
    amount_range=(200.0, 8000.0),
    total_past_payments_range=(2, 20),
    past_success_rate_range=(0.05, 0.35),
    base_recovery_probability=0.10,
    preferred_recovery_channel="none_or_escalate",
    nuance_note="Low past recovery rate and high retry count signal low probability; auto-retry wastes gateway fees."
)


HIGH_VALUE_LINK_RESPONDER = ArchetypeConfig(
    name="high_value_link_responder",
    description=(
        "B2B or premium consumer transactions with large INR amounts (>₹20,000). "
        "Fails on auto-retry due to strict bank authentication limits (3DS/OTP), but responds "
        "very effectively when sent an explicit interactive payment link (~65% recovery)."
    ),
    event_type_distribution={
        "payment_failure": 0.70,
        "subscription_failure": 0.30,
    },
    failure_reason_distribution={
        "card_declined": 0.40,
        "network_error": 0.30,
        "insufficient_funds": 0.30,
    },
    attempt_count_range=(1, 3),
    days_since_last_attempt_range=(0.5, 3.0),
    amount_range=(25000.0, 250000.0),
    total_past_payments_range=(5, 30),
    past_success_rate_range=(0.60, 0.90),
    base_recovery_probability=0.65,
    preferred_recovery_channel="payment_link",
    nuance_note="High transaction amount (>= ₹20,000). Auto-retries fail due to 2FA; sending payment link yields high recovery."
)


SLOW_BUT_RELIABLE_PAYER = ArchetypeConfig(
    name="slow_but_reliable_payer",
    description=(
        "Corporate or invoiced clients with overdue payment terms. "
        "Does not recover on immediate card retry, but consistently settles (~70% recovery) "
        "after receiving a formal invoice reminder / WhatsApp payment follow-up."
    ),
    event_type_distribution={
        "overdue_invoice": 0.85,
        "payment_failure": 0.15,
    },
    failure_reason_distribution={
        "overdue": 0.85,
        "insufficient_funds": 0.15,
    },
    attempt_count_range=(1, 3),
    days_since_last_attempt_range=(5.0, 30.0),
    amount_range=(10000.0, 100000.0),
    total_past_payments_range=(4, 25),
    past_success_rate_range=(0.70, 0.95),
    base_recovery_probability=0.70,
    preferred_recovery_channel="reminder_notice",
    nuance_note="Overdue invoice pattern; requires formal reminder/notice rather than instant retry."
)


CHECKOUT_ABANDONER = ArchetypeConfig(
    name="checkout_abandoner",
    description=(
        "Shoppers who drop off at the final checkout step. "
        "Low response to auto-retries (since order wasn't submitted), but moderate recovery (~40%) "
        "when re-engaged with a targeted reminder email or discount link."
    ),
    event_type_distribution={
        "checkout_abandonment": 1.0,
    },
    failure_reason_distribution={
        "abandoned": 1.0,
    },
    attempt_count_range=(1, 2),
    days_since_last_attempt_range=(0.2, 3.0),
    amount_range=(450.0, 12000.0),
    total_past_payments_range=(0, 10),
    past_success_rate_range=(0.20, 0.70),
    base_recovery_probability=0.40,
    preferred_recovery_channel="checkout_reminder",
    nuance_note="Abandonment event; retry is inapplicable. Requires cart recovery reminder / payment link."
)


ARCHETYPES: Dict[str, ArchetypeConfig] = {
    "reliable_temporary_glitch": RELIABLE_TEMPORARY_GLITCH,
    "chronic_failer": CHRONIC_FAILER,
    "high_value_link_responder": HIGH_VALUE_LINK_RESPONDER,
    "slow_but_reliable_payer": SLOW_BUT_RELIABLE_PAYER,
    "checkout_abandoner": CHECKOUT_ABANDONER,
}
