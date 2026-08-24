"""
Pytest Suite for RecoverAI Data Generator & Schema Validation (Phase 1).

Verifies:
1. Batch sampling produced roughly equal archetype distribution mix.
2. Observed recovery rates per archetype match configured base probabilities within statistical tolerance.
3. No required fields are null.
4. Amounts, attempt counts, and historical rates meet positive boundary constraints.
5. policy/rules.yaml loads correctly with all specified real-world policy constraints.
"""

from collections import Counter
import os
import pytest
import yaml

from data_generation.archetypes import ARCHETYPES
from data_generation.generate_batch import generate_batch
from data_generation.generator import generate_event


def test_batch_archetype_mix():
    """Verify that generating 1000 events produces roughly equal mix across 5 archetypes."""
    n = 1000
    events = generate_batch(n=n, csv_path=None, sqlite_path=None, seed=42)

    assert len(events) == n

    counts = Counter(event.archetype for event in events)
    expected_per_archetype = n / len(ARCHETYPES)  # 200 per archetype

    for archetype_name in ARCHETYPES:
        observed_count = counts[archetype_name]
        # 1000 samples, 5 classes -> standard deviation ~ 12.6
        # Allow a reasonable tolerance band of +/- 50 (150 to 250 events)
        assert 150 <= observed_count <= 250, (
            f"Archetype '{archetype_name}' count {observed_count} out of expected band [150, 250]"
        )


def test_recovery_rates_per_archetype():
    """Verify that observed did_recover rates per archetype fall within reasonable band of base probability."""
    sample_size = 500

    for archetype_name, config in ARCHETYPES.items():
        recovered_count = 0
        for _ in range(sample_size):
            event = generate_event(archetype_name)
            if event.did_recover:
                recovered_count += 1

        observed_rate = recovered_count / sample_size
        target_rate = config.base_recovery_probability

        # Band tolerance of +/- 0.08 (8 percentage points)
        assert abs(observed_rate - target_rate) < 0.08, (
            f"Archetype '{archetype_name}': observed recovery rate {observed_rate:.3f} "
            f"deviates significantly from base probability {target_rate}"
        )


def test_no_null_required_fields():
    """Verify that no required schema field is ever null in generated events."""
    events = [generate_event(arch) for arch in list(ARCHETYPES.keys()) * 10]

    for event in events:
        assert event.event_id is not None and len(event.event_id) > 0
        assert event.event_type is not None
        assert event.timestamp is not None
        assert event.amount is not None
        assert event.customer_id is not None and len(event.customer_id) > 0
        assert event.failure_reason is not None
        assert event.attempt_count is not None
        assert event.days_since_last_attempt is not None
        assert event.customer_history_summary is not None
        assert event.customer_history_summary.total_past_payments is not None
        assert event.customer_history_summary.past_successful_payments is not None
        assert event.customer_history_summary.past_recovery_rate is not None
        assert event.archetype is not None
        assert event.did_recover is not None


def test_positive_amounts_and_attempts():
    """Verify that amounts and attempt counts are strictly positive."""
    events = [generate_event(arch) for arch in list(ARCHETYPES.keys()) * 20]

    for event in events:
        assert event.amount > 0.0, f"Amount must be positive, got {event.amount}"
        assert event.attempt_count >= 1, f"Attempt count must be >= 1, got {event.attempt_count}"
        assert event.days_since_last_attempt >= 0.0, f"Days since last attempt must be >= 0, got {event.days_since_last_attempt}"
        assert event.customer_history_summary.total_past_payments >= 0
        assert event.customer_history_summary.past_successful_payments >= 0
        assert 0.0 <= event.customer_history_summary.past_recovery_rate <= 1.0


def test_policy_rules_yaml_validity():
    """Verify policy/rules.yaml exists, parses correctly, and contains all required constraints."""
    rules_path = os.path.join(os.path.dirname(__file__), "..", "policy", "rules.yaml")
    assert os.path.exists(rules_path), f"policy/rules.yaml not found at {rules_path}"

    with open(rules_path, "r", encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    assert rules.get("max_retry_attempts") == 3
    assert rules.get("retry_cooldown_minutes") == 30
    assert rules.get("escalation_after_failed_attempts") == 4
    assert rules.get("payment_link_threshold_amount") == 20000
    assert rules.get("stop_if_recovery_probability_below") == 0.20
    assert rules.get("max_daily_contact_attempts_per_customer") == 2
