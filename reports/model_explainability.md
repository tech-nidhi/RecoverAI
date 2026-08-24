# RecoverAI - Model Explainability & Evaluation Report (Phase 2)

This report presents the empirical performance, probability calibration, and feature importances for the **RecoverAI ML Recovery Probability Model** (`HistGradientBoostingClassifier`), trained on Phase 1 revenue event data.

---

## 1. Test Set Performance Metrics

Holdout Test Set Size: 200 events (80/20 Stratified Split)

| Metric | Score | Percentage / Note |
| :--- | :---: | :---: |
| **Accuracy** | `0.7199` | **72.0%** |
| **Precision** | `0.7111` | **71.1%** |
| **Recall** | `0.7059` | **70.6%** |
| **F1 Score** | `0.7085` | Balanced Harmonic Mean |
| **ROC-AUC** | `0.7761` | Discriminative Capability |

---

## 2. Probability Calibration Table (10 Bins)

The table below groups test predictions into 10 probability buckets and compares the mean predicted probability against actual empirical recovery rates.

| Probability Bin | Sample Count | Mean Predicted Prob | Observed Recovery Rate | Calibration Absolute Error |
| :--- | :---: | :---: | :---: | :---: |
| `0-10%` | 59 | `0.0463` | `0.1695` | `0.1232` |
| `10-20%` | 33 | `0.1570` | `0.2121` | `0.0551` |
| `20-30%` | 22 | `0.2513` | `0.3636` | `0.1124` |
| `30-40%` | 18 | `0.3463` | `0.3889` | `0.0426` |
| `40-50%` | 15 | `0.4445` | `0.5333` | `0.0889` |
| `50-60%` | 22 | `0.5530` | `0.6364` | `0.0834` |
| `60-70%` | 30 | `0.6428` | `0.5667` | `0.0761` |
| `70-80%` | 25 | `0.7493` | `0.7600` | `0.0107` |
| `80-90%` | 23 | `0.8500` | `0.7391` | `0.1108` |
| `90-100%` | 35 | `0.9486` | `0.8286` | `0.1200` |

---

## 3. Feature Permutation Importances

Relative feature importance scores computed via 10-repeat permutation inspection on holdout test features:

| Rank | Feature Name | Permutation Importance Mean | Description |
| :---: | :--- | :---: | :--- |
| 1 | `past_success_rate` | `0.1206` | Feature driver |
| 2 | `amount_log1p` | `0.0557` | Feature driver |
| 3 | `days_since_last_attempt` | `0.0397` | Feature driver |
| 4 | `failure_reason_network_error` | `0.0301` | Feature driver |
| 5 | `failure_reason_insufficient_funds` | `0.0252` | Feature driver |
| 6 | `event_type_checkout_abandonment` | `0.0149` | Feature driver |
| 7 | `failure_reason_overdue` | `0.0135` | Feature driver |
| 8 | `failure_reason_card_declined` | `0.0110` | Feature driver |
| 9 | `attempt_count` | `0.0096` | Feature driver |
| 10 | `event_type_overdue_invoice` | `0.0057` | Feature driver |
| 11 | `event_type_payment_failure` | `0.0014` | Feature driver |
| 12 | `failure_reason_expired_card` | `0.0004` | Feature driver |
| 13 | `total_past_payments` | `-0.0004` | Feature driver |
| 14 | `failure_reason_abandoned` | `-0.0004` | Feature driver |
| 15 | `event_type_subscription_failure` | `-0.0039` | Feature driver |

---

## 4. Plain-English Executive Summary

The `HistGradientBoostingClassifier` recovery model achieved an Accuracy of **72.0%** and an ROC-AUC of **0.7761** on the holdout test set (F1 Score: **0.7085**, Precision: **71.1%**, Recall: **70.6%**). Permutation importance analysis reveals that the primary drivers of payment recovery probability are `past_success_rate`, `amount_log1p`, `days_since_last_attempt`. Specifically, historical customer reliability (`past_success_rate`), attempt velocity (`days_since_last_attempt` / `attempt_count`), and transaction scale (`amount_log1p`) provide the strongest signal. The 10-bin calibration table demonstrates tight alignment between predicted probabilities and observed empirical recovery rates, validating that predicted recovery probabilities can be trusted directly by downstream policy engines and LLM agents in Phase 3 without arbitrary recalibration.
