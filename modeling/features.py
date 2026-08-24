"""
Feature Engineering Module for RecoverAI (Phase 2).

Converts raw RevenueEvent dataframes into ML-ready numerical feature matrices,
enforcing strict exclusion of ground-truth target labels (archetype and did_recover).
"""

import numpy as np
import pandas as pd

# Standard categorical values for consistent one-hot encoding alignment
EVENT_TYPES = [
    "payment_failure",
    "checkout_abandonment",
    "subscription_failure",
    "overdue_invoice",
]

FAILURE_REASONS = [
    "insufficient_funds",
    "card_declined",
    "network_error",
    "expired_card",
    "abandoned",
    "overdue",
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforms raw RevenueEvent dataframe into a model-ready numerical feature matrix.

    Args:
        df: Pandas DataFrame containing raw RevenueEvent records.

    Returns:
        pd.DataFrame: Processed numerical feature matrix for model training/prediction.

    Raises:
        ValueError: If 'archetype' or 'did_recover' target labels leak into the output feature set.
    """
    features = pd.DataFrame(index=df.index)

    # 1. Log-transform financial amount (log1p to handle skewness)
    features["amount_log1p"] = np.log1p(df["amount"].astype(float))

    # 2. Direct numeric features
    features["attempt_count"] = df["attempt_count"].astype(int)
    features["days_since_last_attempt"] = df["days_since_last_attempt"].astype(float)

    # 3. Handle historical payment performance metrics
    if "total_past_payments" in df.columns and "past_successful_payments" in df.columns:
        total = df["total_past_payments"].astype(float)
        successful = df["past_successful_payments"].astype(float)
    elif "customer_history_summary" in df.columns:
        # Extract from nested dict if present
        def parse_summary(val):
            if isinstance(val, dict):
                return val
            import json
            try:
                return json.loads(val)
            except Exception:
                return {"total_past_payments": 0, "past_successful_payments": 0}

        summaries = df["customer_history_summary"].apply(parse_summary)
        total = pd.Series([s.get("total_past_payments", 0) for s in summaries], index=df.index).astype(float)
        successful = pd.Series([s.get("past_successful_payments", 0) for s in summaries], index=df.index).astype(float)
    else:
        total = pd.Series(0.0, index=df.index)
        successful = pd.Series(0.0, index=df.index)

    features["total_past_payments"] = total

    # Derive past_success_rate with neutral prior (0.5) when total_past_payments == 0
    neutral_prior = 0.5
    features["past_success_rate"] = np.where(
        total > 0,
        successful / np.maximum(total, 1.0),
        neutral_prior
    )

    # 4. One-hot encode event_type
    for et in EVENT_TYPES:
        features[f"event_type_{et}"] = (df["event_type"] == et).astype(int)

    # 5. One-hot encode failure_reason
    for fr in FAILURE_REASONS:
        features[f"failure_reason_{fr}"] = (df["failure_reason"] == fr).astype(int)

    # -------------------------------------------------------------------------
    # STRICT GROUND-TRUTH SAFETY ASSERTION
    # Ensure ground-truth labels and archetype metadata are strictly excluded!
    # -------------------------------------------------------------------------
    prohibited_cols = ["archetype", "did_recover"]
    for col in prohibited_cols:
        if col in features.columns:
            raise ValueError(
                f"CRITICAL DATA LEAKAGE: Prohibited ground-truth column '{col}' "
                f"found in feature matrix! Must be explicitly excluded."
            )

    return features
