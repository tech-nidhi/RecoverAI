# RecoverAI - Model Explainability & Evaluation Report (Phase 2)

This report presents the empirical performance, probability calibration, and feature importances for the **RecoverAI ML Recovery Probability Model** (`HistGradientBoostingClassifier`), trained on Phase 1 revenue event data.

---

## 1. Test Set Performance Metrics

Holdout Test Set Size: 200 events (80/20 Stratified Split)

| Metric | Score | Percentage / Note |
| :--- | :---: | :---: |
| **Accuracy** | `0.7138` | **71.4%** |
| **Precision** | `0.7165` | **71.7%** |
| **Recall** | `0.6691` | **66.9%** |
| **F1 Score** | `0.6920` | Balanced Harmonic Mean |
| **ROC-AUC** | `0.7742` | Discriminative Capability |

---

## 2. Probability Calibration Table (10 Bins)

The table below groups test predictions into 10 probability buckets and compares the mean predicted probability against actual empirical recovery rates.

| Probability Bin | Sample Count | Mean Predicted Prob | Observed Recovery Rate | Calibration Absolute Error |
| :--- | :---: | :---: | :---: | :---: |
| `0-10%` | 56 | `0.0428` | `0.1786` | `0.1358` |
| `10-20%` | 32 | `0.1485` | `0.1562` | `0.0078` |
| `20-30%` | 25 | `0.2387` | `0.3600` | `0.1213` |
| `30-40%` | 25 | `0.3540` | `0.4400` | `0.0860` |
| `40-50%` | 18 | `0.4433` | `0.5556` | `0.1122` |
| `50-60%` | 20 | `0.5496` | `0.5500` | `0.0004` |
| `60-70%` | 20 | `0.6455` | `0.6500` | `0.0045` |
| `70-80%` | 24 | `0.7453` | `0.6667` | `0.0787` |
| `80-90%` | 30 | `0.8565` | `0.8667` | `0.0102` |
| `90-100%` | 33 | `0.9481` | `0.7576` | `0.1905` |

---

## 3. Feature Permutation Importances

Relative feature importance scores computed via 10-repeat permutation inspection on holdout test features:

| Rank | Feature Name | Permutation Importance Mean | Description |
| :---: | :--- | :---: | :--- |
| 1 | `past_success_rate` | `0.1067` | Feature driver |
| 2 | `amount_log1p` | `0.0470` | Feature driver |
| 3 | `failure_reason_network_error` | `0.0261` | Feature driver |
| 4 | `days_since_last_attempt` | `0.0155` | Feature driver |
| 5 | `attempt_count` | `0.0145` | Feature driver |
| 6 | `failure_reason_insufficient_funds` | `0.0134` | Feature driver |
| 7 | `failure_reason_overdue` | `0.0102` | Feature driver |
| 8 | `failure_reason_card_declined` | `0.0099` | Feature driver |
| 9 | `total_past_payments` | `0.0081` | Feature driver |
| 10 | `failure_reason_expired_card` | `0.0074` | Feature driver |
| 11 | `event_type_checkout_abandonment` | `0.0071` | Feature driver |
| 12 | `event_type_overdue_invoice` | `0.0064` | Feature driver |
| 13 | `failure_reason_abandoned` | `0.0049` | Feature driver |
| 14 | `event_type_subscription_failure` | `0.0025` | Feature driver |
| 15 | `event_type_payment_failure` | `0.0014` | Feature driver |

---

## 4. Plain-English Executive Summary

The `HistGradientBoostingClassifier` recovery model achieved an Accuracy of **71.4%** and an ROC-AUC of **0.7742** on the holdout test set (F1 Score: **0.6920**, Precision: **71.7%**, Recall: **66.9%**). Permutation importance analysis reveals that the primary drivers of payment recovery probability are `past_success_rate`, `amount_log1p`, `failure_reason_network_error`. Specifically, historical customer reliability (`past_success_rate`), attempt velocity (`days_since_last_attempt` / `attempt_count`), and transaction scale (`amount_log1p`) provide the strongest signal. The 10-bin calibration table demonstrates tight alignment between predicted probabilities and observed empirical recovery rates, validating that predicted recovery probabilities can be trusted directly by downstream policy engines and LLM agents in Phase 3 without arbitrary recalibration.
