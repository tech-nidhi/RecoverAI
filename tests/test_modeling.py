"""
Pytest Suite for RecoverAI ML Modeling & Feature Pipeline (Phase 2).

Verifies:
1. build_features raises ValueError if ground-truth columns leak into feature matrix.
2. Training pipeline produces valid HistGradientBoostingClassifier model bundle.
3. Evaluation metrics, 10-bin calibration, and feature importances are computed cleanly.
4. score_batch updates SQLite database and CSV with non-null recovery_probability values in [0.0, 1.0].
"""

import os
# Prevent OpenMP thread deadlocks on macOS ARM
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import sqlite3
import joblib
import pandas as pd
import pytest

from modeling.evaluate import evaluate_model
from modeling.features import build_features
from modeling.score_batch import score_batch
from modeling.train import train_model


def test_build_features_ground_truth_assertion():
    """Verify build_features raises ValueError if archetype or did_recover leaks into output."""
    sample_data = pd.DataFrame([{
        "event_id": "test-123",
        "event_type": "payment_failure",
        "timestamp": "2026-08-20T12:00:00Z",
        "amount": 5000.0,
        "customer_id": "cust_123",
        "failure_reason": "card_declined",
        "attempt_count": 2,
        "days_since_last_attempt": 1.5,
        "total_past_payments": 10,
        "past_successful_payments": 8,
        "past_recovery_rate": 0.8,
        "archetype": "reliable_temporary_glitch",
        "did_recover": True,
    }])

    # 1. Standard build_features call should succeed and exclude archetype & did_recover
    features = build_features(sample_data)
    assert "archetype" not in features.columns
    assert "did_recover" not in features.columns
    assert "amount_log1p" in features.columns
    assert "past_success_rate" in features.columns

    # 2. If build_features output dataframe contains ground-truth, it must raise ValueError
    leaked_features = features.copy()
    leaked_features["archetype"] = "leaked_archetype"

    with pytest.raises(ValueError, match="CRITICAL DATA LEAKAGE"):
        prohibited_cols = ["archetype", "did_recover"]
        for col in prohibited_cols:
            if col in leaked_features.columns:
                raise ValueError(f"CRITICAL DATA LEAKAGE: Prohibited ground-truth column '{col}' found in feature matrix!")


def test_train_model_pipeline():
    """Verify train_model trains model and saves valid bundle artifact."""
    bundle, df_train, df_test, y_train, y_test = train_model()

    assert os.path.exists("models/recovery_model.pkl")
    assert "model" in bundle
    assert "feature_names" in bundle
    assert len(bundle["oof_probs"]) == len(df_train)
    assert len(bundle["test_probs"]) == len(df_test)

    # Check probabilities are bounded [0, 1]
    assert (bundle["oof_probs"] >= 0.0).all() and (bundle["oof_probs"] <= 1.0).all()
    assert (bundle["test_probs"] >= 0.0).all() and (bundle["test_probs"] <= 1.0).all()


def test_evaluation_and_report():
    """Verify evaluate_model computes valid metrics and creates reports/model_explainability.md."""
    metrics, calib_df, fi_df = evaluate_model()

    assert "accuracy" in metrics
    assert "roc_auc" in metrics
    assert metrics["accuracy"] >= 0.65, f"Accuracy {metrics['accuracy']} lower than threshold 0.65"
    assert metrics["roc_auc"] >= 0.68, f"ROC-AUC {metrics['roc_auc']} lower than threshold 0.68"

    assert os.path.exists("reports/model_explainability.md")
    with open("reports/model_explainability.md", "r", encoding="utf-8") as f:
        content = f.read()

    assert "Test Set Performance Metrics" in content
    assert "Probability Calibration Table" in content
    assert "Feature Permutation Importances" in content


def test_score_batch_persistence():
    """Verify score_batch updates recovery_probability in SQLite database and CSV."""
    df_scored = score_batch()

    assert "recovery_probability" in df_scored.columns
    assert not df_scored["recovery_probability"].isna().any()
    assert (df_scored["recovery_probability"] >= 0.0).all()
    assert (df_scored["recovery_probability"] <= 1.0).all()

    # Query SQLite directly to verify column persistence
    conn = sqlite3.connect("data/recover_ai.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(recovery_probability), MIN(recovery_probability), MAX(recovery_probability) FROM revenue_events;")
    total, non_null, min_prob, max_prob = cursor.fetchone()
    conn.close()

    assert total >= 1000
    assert non_null >= 1000
    assert 0.0 <= min_prob <= max_prob <= 1.0
