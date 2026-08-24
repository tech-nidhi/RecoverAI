"""
Batch Scoring & Database Persistence Script for RecoverAI (Phase 2).

Populates recovery_probability for every row in the dataset (using out-of-fold predictions
for training set rows to prevent leakage, and direct test predictions for test set rows),
and updates SQLite DB table 'revenue_events' and CSV export.
"""

import json
import os
import sqlite3
import joblib
import pandas as pd

from modeling.features import build_features


def score_batch(
    model_path: str = "models/recovery_model.pkl",
    db_path: str = "data/recover_ai.db",
    csv_path: str = "data/revenue_events.csv"
) -> pd.DataFrame:
    """
    Scores full dataset with recovery probabilities without leakage and persists to SQLite/CSV.
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Saved model bundle not found at {model_path}. Run train.py first.")

    bundle = joblib.load(model_path)
    model = bundle["model"]
    feature_names = bundle["feature_names"]
    oof_probs = bundle["oof_probs"]
    test_probs = bundle["test_probs"]

    # 1. Load full dataset
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM revenue_events", conn)
        conn.close()
    else:
        df = pd.read_csv(csv_path)

    # 2. Assign recovery_probability scores (OOF for train rows, test_probs for test rows)
    recovery_prob_series = pd.Series(index=df.index, dtype=float)

    # Fill train set out-of-fold scores
    for idx, prob in oof_probs.items():
        if idx in recovery_prob_series.index:
            recovery_prob_series.loc[idx] = round(float(prob), 4)

    # Fill test set scores
    for idx, prob in test_probs.items():
        if idx in recovery_prob_series.index:
            recovery_prob_series.loc[idx] = round(float(prob), 4)

    # Fallback for any unassigned indices (if dataset changed)
    missing_indices = recovery_prob_series[recovery_prob_series.isna()].index
    if len(missing_indices) > 0:
        print(f"Scoring {len(missing_indices)} additional records with model.predict_proba...")
        df_missing = df.loc[missing_indices]
        X_missing = build_features(df_missing)[feature_names]
        preds_missing = model.predict_proba(X_missing)[:, 1]
        for idx, prob in zip(missing_indices, preds_missing):
            recovery_prob_series.loc[idx] = round(float(prob), 4)

    df["recovery_probability"] = recovery_prob_series

    # 3. Persist updated dataset to SQLite
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Update SQLite table rows with new recovery_probability
        update_sql = "UPDATE revenue_events SET recovery_probability = ? WHERE event_id = ?"
        update_tuples = [
            (float(row["recovery_probability"]), str(row["event_id"]))
            for _, row in df.iterrows()
        ]
        cursor.executemany(update_sql, update_tuples)
        conn.commit()
        conn.close()
        print(f"✓ Updated recovery_probability in SQLite DB ({db_path}), table 'revenue_events'")

    # 4. Persist updated dataset to CSV
    if os.path.exists(csv_path) or True:
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
        df.to_csv(csv_path, index=False)
        print(f"✓ Updated recovery_probability in CSV: {csv_path}")

    return df


if __name__ == "__main__":
    score_batch()
