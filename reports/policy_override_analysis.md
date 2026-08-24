# RecoverAI - Policy Override Analysis & Agent Decision Report (Phase 3)

This report details the operational performance, action distributions, and deterministic policy guardrail overrides for **RecoverAI Phase 3**.

---

## 1. Executive Summary

- **Total Events Processed**: `1000`
- **Approved LLM Recommendations**: `972` (97.2%)
- **Policy Engine Overrides (Blocked)**: `28` (**2.8%**)

> **Key Takeaway**: The policy engine successfully prevented unsafe, non-compliant, or economically unviable AI recommendations in **2.8%** of events, enforcing regulatory compliance (RBI 2FA, TRAI anti-spam) and financial guardrails.

---

## 2. Final Executed Action Distribution

| Final Executed Action | Event Count | Share of Total | Primary Intent |
| :--- | :---: | :---: | :--- |
| `REMINDER` | 301 | `30.1%` | Standard recovery action |
| `STOP` | 266 | `26.6%` | Standard recovery action |
| `PAYMENT_LINK` | 227 | `22.7%` | Standard recovery action |
| `RETRY` | 178 | `17.8%` | Standard recovery action |
| `ESCALATE` | 28 | `2.8%` | Standard recovery action |

---

## 3. Policy Override Breakdown by Archetype

| Customer Archetype | Total Events | Approved | Blocked (Overridden) | Policy Override Rate | Primary Guardrail Triggered |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `checkout_abandoner` | 212 | 184 | 28 | **`13.2%`** | Hard policy constraint |
| `chronic_failer` | 196 | 196 | 0 | **`0.0%`** | Hard policy constraint |
| `high_value_link_responder` | 206 | 206 | 0 | **`0.0%`** | Hard policy constraint |
| `reliable_temporary_glitch` | 178 | 178 | 0 | **`0.0%`** | Hard policy constraint |
| `slow_but_reliable_payer` | 208 | 208 | 0 | **`0.0%`** | Hard policy constraint |

---

## 4. Policy Guardrail Architecture

The system strictly decouples **AI Recommendation Generation** from **Policy Enforcement**:
1. **LLM Agent (`agent/llm_agent.py`)**: Proposes `recommended_action` and 2-3 sentence reasoning text.
2. **Policy Engine (`policy/policy_engine.py`)**: Evaluates `policy/rules.yaml` rules deterministically. If blocked, substitutes a safe fallback `final_action`.
3. **Audit Log (`agent/decision_log.py`)**: Records every decision into SQLite table `decisions`.
