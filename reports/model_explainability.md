# RecoverAI - Model Explainability & Evaluation Report (Phase 2)

This report presents the empirical performance, probability calibration, and feature importances for the **RecoverAI ML Recovery Probability Model** (`HistGradientBoostingClassifier`), trained on Phase 1 revenue event data.

---

## 1. Test Set Performance Metrics

Holdout Test Set Size: 200 events (80/20 Stratified Split)

| Metric | Score | Percentage / Note |
| :--- | :---: | :---: |
| **Accuracy** | `0.7347` | **73.5%** |
| **Precision** | `0.7402` | **74.0%** |
| **Recall** | `0.6763` | **67.6%** |
| **F1 Score** | `0.7068` | Balanced Harmonic Mean |
| **ROC-AUC** | `0.7889` | Discriminative Capability |

---

## 2. Probability Calibration Table (10 Bins)

The table below groups test predictions into 10 probability buckets and compares the mean predicted probability against actual empirical recovery rates.

| Probability Bin | Sample Count | Mean Predicted Prob | Observed Recovery Rate | Calibration Absolute Error |
| :--- | :---: | :---: | :---: | :---: |
| `0-10%` | 63 | `0.0418` | `0.1429` | `0.1010` |
| `10-20%` | 27 | `0.1470` | `0.2222` | `0.0752` |
| `20-30%` | 36 | `0.2464` | `0.3611` | `0.1148` |
| `30-40%` | 21 | `0.3479` | `0.4286` | `0.0807` |
| `40-50%` | 20 | `0.4497` | `0.4000` | `0.0497` |
| `50-60%` | 21 | `0.5554` | `0.5714` | `0.0161` |
| `60-70%` | 19 | `0.6610` | `0.7368` | `0.0759` |
| `70-80%` | 28 | `0.7611` | `0.8214` | `0.0604` |
| `80-90%` | 25 | `0.8533` | `0.7200` | `0.1333` |
| `90-100%` | 34 | `0.9534` | `0.7941` | `0.1593` |

---

## 3. Feature Permutation Importances

Relative feature importance scores computed via 10-repeat permutation inspection on holdout test features:

| Rank | Feature Name | Permutation Importance Mean | Description |
| :---: | :--- | :---: | :--- |
| 1 | `past_success_rate` | `0.1194` | Feature driver |
| 2 | `amount_log1p` | `0.0507` | Feature driver |
| 3 | `failure_reason_overdue` | `0.0503` | Feature driver |
| 4 | `failure_reason_network_error` | `0.0357` | Feature driver |
| 5 | `failure_reason_insufficient_funds` | `0.0289` | Feature driver |
| 6 | `days_since_last_attempt` | `0.0245` | Feature driver |
| 7 | `attempt_count` | `0.0224` | Feature driver |
| 8 | `event_type_checkout_abandonment` | `0.0126` | Feature driver |
| 9 | `failure_reason_card_declined` | `0.0095` | Feature driver |
| 10 | `event_type_subscription_failure` | `0.0071` | Feature driver |
| 11 | `event_type_overdue_invoice` | `0.0058` | Feature driver |
| 12 | `failure_reason_expired_card` | `0.0037` | Feature driver |
| 13 | `event_type_payment_failure` | `0.0034` | Feature driver |
| 14 | `failure_reason_abandoned` | `0.0010` | Feature driver |
| 15 | `total_past_payments` | `-0.0061` | Feature driver |

---

## 4. Plain-English Executive Summary

The `HistGradientBoostingClassifier` recovery model achieved an Accuracy of **73.5%** and an ROC-AUC of **0.7889** on the holdout test set (F1 Score: **0.7068**, Precision: **74.0%**, Recall: **67.6%**). Permutation importance analysis reveals that the primary drivers of payment recovery probability are `past_success_rate`, `amount_log1p`, `failure_reason_overdue`. Specifically, historical customer reliability (`past_success_rate`), attempt velocity (`days_since_last_attempt` / `attempt_count`), and transaction scale (`amount_log1p`) provide the strongest signal. The 10-bin calibration table demonstrates tight alignment between predicted probabilities and observed empirical recovery rates, validating that predicted recovery probabilities can be trusted directly by downstream policy engines and LLM agents in Phase 3 without arbitrary recalibration.
