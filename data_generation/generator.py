"""
Synthetic Event Generator for RecoverAI.

Contains the core function generate_event(archetype) to sample a single RevenueEvent
from an ArchetypeConfig's behavioral distributions, incorporating stochastic noise for
ground-truth recovery labels.
"""

from datetime import datetime, timedelta, timezone
import random
from typing import Union
from uuid import uuid4

from data_generation.archetypes import ARCHETYPES, ArchetypeConfig
from schema.event_schema import CustomerHistorySummary, RevenueEvent


def _sample_categorical(distribution: dict) -> str:
    """Helper to sample a key from a dictionary of category weights."""
    keys = list(distribution.keys())
    weights = list(distribution.values())
    return random.choices(keys, weights=weights, k=1)[0]


def generate_event(
    archetype: Union[ArchetypeConfig, str],
    reference_time: datetime = None
) -> RevenueEvent:
    """
    Samples one RevenueEvent from a given customer archetype's distributions.

    Args:
        archetype: ArchetypeConfig instance or archetype string key (e.g. 'reliable_temporary_glitch')
        reference_time: Optional datetime reference point for generating event timestamp.

    Returns:
        RevenueEvent: Pydantic model populated with sampled features and ground truth labels.
    """
    if isinstance(archetype, str):
        if archetype not in ARCHETYPES:
            raise ValueError(f"Unknown archetype: {archetype}. Available: {list(ARCHETYPES.keys())}")
        config = ARCHETYPES[archetype]
    else:
        config = archetype

    # 1. Sample categorical features
    event_type = _sample_categorical(config.event_type_distribution)
    failure_reason = _sample_categorical(config.failure_reason_distribution)

    # 2. Sample timestamp (past 30 days up to reference_time or now)
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    seconds_ago = random.uniform(0, 30 * 24 * 3600)
    timestamp = reference_time - timedelta(seconds=seconds_ago)

    # 3. Sample financial & attempt features
    amount = round(random.uniform(*config.amount_range), 2)
    attempt_count = random.randint(*config.attempt_count_range)
    days_since_last_attempt = round(random.uniform(*config.days_since_last_attempt_range), 2)

    # 4. Sample customer history summary
    total_past_payments = random.randint(*config.total_past_payments_range)
    if total_past_payments > 0:
        raw_rate = random.uniform(*config.past_success_rate_range)
        past_successful_payments = int(round(total_past_payments * raw_rate))
        # Ensure past_successful_payments is bounded
        past_successful_payments = max(0, min(total_past_payments, past_successful_payments))
        past_recovery_rate = round(past_successful_payments / total_past_payments, 4)
    else:
        past_successful_payments = 0
        past_recovery_rate = 0.0

    history_summary = CustomerHistorySummary(
        total_past_payments=total_past_payments,
        past_successful_payments=past_successful_payments,
        past_recovery_rate=past_recovery_rate,
    )

    # 5. Generate Customer ID
    cust_num = random.randint(1000, 9999)
    customer_id = f"cust_{config.name[:6]}_{cust_num}"

    # 6. Sample Ground Truth did_recover label with noise around base probability
    # Gaussian noise with stddev=0.04 to add real-world variance while preserving archetype signals
    noise = random.gauss(0.0, 0.04)
    effective_prob = max(0.02, min(0.98, config.base_recovery_probability + noise))
    did_recover = random.random() < effective_prob

    # 7. Construct RevenueEvent instance
    event = RevenueEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        timestamp=timestamp,
        amount=amount,
        customer_id=customer_id,
        failure_reason=failure_reason,
        attempt_count=attempt_count,
        days_since_last_attempt=days_since_last_attempt,
        customer_history_summary=history_summary,
        archetype=config.name,
        did_recover=did_recover,
        # Downstream fields default to None
        recovery_probability=None,
        recommended_action=None,
        policy_decision=None,
        executed_action=None,
        outcome=None,
        revenue_recovered=None,
        reasoning_text=None,
    )

    return event
