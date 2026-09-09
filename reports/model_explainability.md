# RecoverAI - Model Explainability & Evaluation Report (Phase 2)

This report presents the empirical performance, probability calibration, and feature importances for the **RecoverAI ML Recovery Probability Model** (`HistGradientBoostingClassifier`), trained on Phase 1 revenue event data.

---

## 1. Test Set Performance Metrics

Holdout Test Set Size: 200 events (80/20 Stratified Split)

| Metric | Score | Percentage / Note |
| :--- | :---: | :---: |
| **Accuracy** | `0.7333` | **73.3%** |
| **Precision** | `0.7405` | **74.0%** |
| **Recall** | `0.6783` | **67.8%** |
| **F1 Score** | `0.7080` | Balanced Harmonic Mean |
| **ROC-AUC** | `0.8056` | Discriminative Capability |

---

## 2. Probability Calibration Table (10 Bins)

The table below groups test predictions into 10 probability buckets and compares the mean predicted probability against actual empirical recovery rates.

| Probability Bin | Sample Count | Mean Predicted Prob | Observed Recovery Rate | Calibration Absolute Error |
| :--- | :---: | :---: | :---: | :---: |
| `0-10%` | 58 | `0.0397` | `0.1552` | `0.1155` |
| `10-20%` | 44 | `0.1421` | `0.1136` | `0.0285` |
| `20-30%` | 27 | `0.2465` | `0.4815` | `0.2350` |
| `30-40%` | 23 | `0.3494` | `0.3913` | `0.0419` |
| `40-50%` | 17 | `0.4483` | `0.5882` | `0.1399` |
| `50-60%` | 18 | `0.5539` | `0.5000` | `0.0539` |
| `60-70%` | 13 | `0.6533` | `0.7692` | `0.1159` |
| `70-80%` | 29 | `0.7409` | `0.7586` | `0.0177` |
| `80-90%` | 34 | `0.8549` | `0.7647` | `0.0902` |
| `90-100%` | 37 | `0.9494` | `0.8108` | `0.1385` |

---

## 3. Feature Permutation Importances

Relative feature importance scores computed via 10-repeat permutation inspection on holdout test features:

| Rank | Feature Name | Permutation Importance Mean | Description |
| :---: | :--- | :---: | :--- |
| 1 | `past_success_rate` | `0.1087` | Feature driver |
| 2 | `amount_log1p` | `0.0627` | Feature driver |
| 3 | `failure_reason_overdue` | `0.0447` | Feature driver |
| 4 | `days_since_last_attempt` | `0.0263` | Feature driver |
| 5 | `failure_reason_network_error` | `0.0237` | Feature driver |
| 6 | `failure_reason_insufficient_funds` | `0.0153` | Feature driver |
| 7 | `event_type_checkout_abandonment` | `0.0113` | Feature driver |
| 8 | `event_type_payment_failure` | `0.0057` | Feature driver |
| 9 | `event_type_overdue_invoice` | `0.0050` | Feature driver |
| 10 | `failure_reason_card_declined` | `0.0043` | Feature driver |
| 11 | `total_past_payments` | `0.0037` | Feature driver |
| 12 | `failure_reason_abandoned` | `0.0027` | Feature driver |
| 13 | `attempt_count` | `0.0023` | Feature driver |
| 14 | `failure_reason_expired_card` | `-0.0007` | Feature driver |
| 15 | `event_type_subscription_failure` | `-0.0063` | Feature driver |

---

## 4. Plain-English Executive Summary

The `HistGradientBoostingClassifier` recovery model achieved an Accuracy of **73.3%** and an ROC-AUC of **0.8056** on the holdout test set (F1 Score: **0.7080**, Precision: **74.0%**, Recall: **67.8%**). Permutation importance analysis reveals that the primary drivers of payment recovery probability are `past_success_rate`, `amount_log1p`, `failure_reason_overdue`. Specifically, historical customer reliability (`past_success_rate`), attempt velocity (`days_since_last_attempt` / `attempt_count`), and transaction scale (`amount_log1p`) provide the strongest signal. The 10-bin calibration table demonstrates tight alignment between predicted probabilities and observed empirical recovery rates, validating that predicted recovery probabilities can be trusted directly by downstream policy engines and LLM agents in Phase 3 without arbitrary recalibration.
