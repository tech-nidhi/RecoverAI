"""
Model Training & Out-of-Fold Cross-Validation Script for RecoverAI (Phase 2).

Loads revenue event records, performs stratified 80/20 train/test split by archetype,
trains a HistGradientBoostingClassifier, generates 5-fold out-of-fold probabilities
on training data to prevent leakage, and persists model artifacts.
"""

import os
# Prevent OpenMP thread deadlocks on macOS ARM
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import sqlite3
import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, train_test_split

from modeling.features import build_features


def train_model(
    db_path: str = "data/recover_ai.db",
    csv_path: str = "data/revenue_events.csv",
    model_save_path: str = "models/recovery_model.pkl",
    random_state: int = 42
):
    """
    Trains HistGradientBoostingClassifier model with 5-fold out-of-fold probability scoring.
    """
    # 1. Load dataset from SQLite or CSV fallback
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM revenue_events", conn)
        conn.close()
        print(f"Loaded {len(df)} records from SQLite DB: {db_path}")
    elif os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        print(f"Loaded {len(df)} records from CSV: {csv_path}")
    else:
        raise FileNotFoundError(
            f"Neither SQLite DB ({db_path}) nor CSV ({csv_path}) found. "
            f"Run python -m data_generation.generate_batch first."
        )

    # Ensure required target & stratify columns exist
    if "did_recover" not in df.columns or "archetype" not in df.columns:
        raise KeyError("Dataset must contain 'did_recover' label and 'archetype' stratify column.")

    y = df["did_recover"].astype(int).values
    archetypes = df["archetype"].values

    # 2. Perform 80/20 Stratified train/test split by archetype
    df_train, df_test, y_train, y_test = train_test_split(
        df,
        y,
        test_size=0.20,
        random_state=random_state,
        stratify=archetypes
    )

    train_indices = df_train.index.values
    test_indices = df_test.index.values

    # 3. Build model-ready feature matrices (strictly excluding ground-truth columns)
    X_train = build_features(df_train)
    X_test = build_features(df_test)

    feature_names = list(X_train.columns)
    print(f"Engineered {len(feature_names)} features: {feature_names}")

    # 4. Out-of-fold (OOF) 5-fold probability scoring on training set
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
    oof_probs = pd.Series(index=df_train.index, dtype=float)

    print("Running 5-fold Stratified Cross-Validation for Out-Of-Fold (OOF) training probabilities...")
    for fold, (train_fold_idx, val_fold_idx) in enumerate(skf.split(X_train, y_train), 1):
        X_tr_fold = X_train.iloc[train_fold_idx]
        y_tr_fold = y_train[train_fold_idx]
        X_val_fold = X_train.iloc[val_fold_idx]

        fold_model = HistGradientBoostingClassifier(
            max_iter=100, random_state=random_state + fold
        )
        fold_model.fit(X_tr_fold, y_tr_fold)

        # Predict probability for positive class (did_recover == True)
        val_preds = fold_model.predict_proba(X_val_fold)[:, 1]
        oof_probs.iloc[val_fold_idx] = val_preds

    # 5. Train final HistGradientBoostingClassifier on full training set
    print("Training final HistGradientBoostingClassifier model on full 80% training split...")
    final_model = HistGradientBoostingClassifier(
        max_iter=100, random_state=random_state
    )
    final_model.fit(X_train, y_train)

    test_probs = final_model.predict_proba(X_test)[:, 1]

    # 6. Save model bundle
    os.makedirs(os.path.dirname(os.path.abspath(model_save_path)), exist_ok=True)
    bundle = {
        "model": final_model,
        "feature_names": feature_names,
        "train_indices": train_indices,
        "test_indices": test_indices,
        "oof_probs": oof_probs,
        "test_probs": pd.Series(test_probs, index=df_test.index),
    }

    joblib.dump(bundle, model_save_path)
    print(f"✓ Model bundle successfully saved to: {model_save_path}")

    return bundle, df_train, df_test, y_train, y_test


if __name__ == "__main__":
    train_model()
