# RecoverAI

## AI-Powered Revenue Recovery Control Plane

RecoverAI is a production-oriented revenue recovery control plane for payment failures and other revenue leakage events.

It closes the loop from **detection → diagnosis → decision → governed intervention → safe execution → recovery → audit → measured impact**.

The key design principle is simple:

> **AI recommends. Deterministic policy decides. Governance authorizes. Idempotency protects. Audit proves. Analytics measures.**

---

## The Problem

Revenue loss rarely happens in one clean step.

A payment can fail, a checkout can be abandoned, a subscription can lapse, or an invoice can become overdue. Traditional recovery systems often stop at detection or send generic retries.

RecoverAI treats recovery as a controlled decision system.

It answers:

- What revenue is at risk?
- How likely is this case to recover?
- Which intervention should be attempted?
- Is that intervention allowed by policy?
- Does it require human approval?
- Can it be executed safely without duplicate financial actions?
- What actually happened?
- How much incremental recovery did the intervention generate?

---

## Core Architecture

```text
                         RAZORPAY
                            |
                     Webhook / Event
                            |
                            v
                 +----------------------+
                 | Webhook Gateway      |
                 | HMAC Validation      |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 | Idempotency Gateway  |
                 | Duplicate Protection |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 | ML Risk Engine       |
                 | Recovery Probability |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 | Deterministic Policy |
                 | Engine               |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 | Governance Layer     |
                 | Limits / Approval /  |
                 | Kill Switch          |
                 +----------+-----------+
                            |
                       +----+----+
                       |         |
                     AUTO      HUMAN
                       |       APPROVAL
                       +----+----+
                            |
                            v
                 +----------------------+
                 | Safe Execution       |
                 | Idempotency / Retry  |
                 | Provider Verification|
                 +----------+-----------+
                            |
                            v
                         RECOVERY
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
        Audit Trail    ROI / Impact    AI Copilot
                        Analytics
```

---

## Feature Inventory

### 1. Event-Driven Webhook Ingestion

- Razorpay webhook listener
- Supported lifecycle events:
  - `payment.failed`
  - `payment.authorized`
  - `payment.captured`
  - `order.paid`
  - `payment_link.paid`
- HMAC SHA-256 signature validation
- Payload normalization into a common internal event schema
- Development simulator for deterministic failure/recovery scenarios

### 2. ML Risk Scoring

RecoverAI predicts recovery probability from transaction and customer context including:

- transaction amount
- failure reason
- attempt count
- time since previous attempt
- historical customer recovery behavior

The model produces a recovery probability between 0 and 1.

### 3. Deterministic Policy Engine

The ML/LLM layer does not have authority to execute financial actions.

The Policy Engine enforces hard boundaries such as:

- maximum retries
- cooldown period
- human approval threshold
- action eligibility

### 4. Governance and Human Approval

- Global automation kill switch
- Per-action automation controls
- High-value human approval workflow
- Daily automated exposure limit
- Governance decision logging

When automation is paused, events continue to be observed and audited. Financial execution stops.

### 5. Safe Financial Execution

RecoverAI protects against duplicate or ambiguous execution through:

- database-level webhook deduplication
- deterministic action idempotency keys
- explicit execution state machine
- `UNKNOWN` state for ambiguous provider/network outcomes
- provider-state verification
- safe retries
- governance checks before retry

The system does not interpret a timeout as an automatic failure.

### 6. Recovery Intelligence

RecoverAI measures more than raw recovered revenue.

It estimates:

- observed recovery
- baseline/organic recovery
- incremental recovery
- execution cost
- net value
- estimated ROI
- intervention lift
- segment-level performance

The system explicitly labels model-based attribution as estimated unless supported by experimental evidence.

### 7. Experiments and Counterfactual Simulation

- Control vs treatment recovery experiments
- Intervention performance comparison
- Counterfactual policy simulation
- Estimated recovery lift
- Estimated incremental revenue
- Intervention volume projections

### 8. AI Operations Copilot

The Copilot is a tool-calling operations interface over the RecoverAI control plane.

It can:

- investigate transactions
- explain policy decisions
- analyze recovery drops
- identify revenue-at-risk cases
- compare interventions
- inspect execution failures
- explain ROI
- check system health
- run simulations
- provide evidence-backed answers

The LLM does not receive arbitrary SQL access and cannot bypass policy/governance.

Mutating actions require explicit confirmation.

### 9. Opportunity Recovery Matrix

Recovery opportunities are organized by:

- payment failure
- checkout abandonment
- subscription failure
- overdue invoice

Cases are ranked using expected recoverable value.

### 10. Audit Trail

RecoverAI records:

- webhook processing
- duplicate event suppression
- policy decisions
- governance changes
- human approvals
- execution attempts
- retries
- provider verification
- recovery outcomes

The audit trail provides a transaction-level explanation of what happened and why.

---

## Safety Model

RecoverAI deliberately separates intelligence from authority.

```text
AI / ML
  |
  | recommendation
  v
Policy Engine
  |
  | deterministic decision
  v
Governance
  |
  | authorization
  v
Execution
  |
  | idempotent action
  v
Provider
```

An LLM recommendation cannot directly execute a financial action.

This prevents an AI model from becoming an uncontrolled financial authority.

---

## Example Recovery Flow

Consider a failed payment worth ₹2,45,033.

```text
1. Razorpay sends payment.failed
2. Signature is verified
3. Event passes idempotency check
4. RecoverAI creates a recovery case
5. ML model estimates recovery probability
6. Policy Engine evaluates eligible actions
7. Governance checks limits and approval requirements
8. High-value action requests human approval
9. Approved action receives a deterministic idempotency key
10. Execution begins
11. Provider/network timeout creates UNKNOWN state
12. Provider state is verified
13. Existing provider success prevents duplicate execution
14. Recovery outcome is recorded
15. Audit Trail records the complete trace
16. Recovery Intelligence calculates estimated incremental impact
17. Copilot can explain the entire transaction
```

---

## AI Copilot Example

**Operator:**

> Why was the highest-value recovery blocked?

**RecoverAI Copilot:**

> The ₹4.82L recovery was blocked because the daily automated exposure limit would have been exceeded.
>
> Current exposure: ₹9.42L / ₹10L  
> Requested action: ₹1.12L  
> Remaining capacity: ₹58K  
> Decision: BLOCKED

The answer is generated from structured RecoverAI data, not invented by the LLM.

---

## Reliability

The project currently has:

**64 / 64 automated tests passing**

The test suite covers the safety-critical behavior including:

- webhook validation
- duplicate protection
- idempotent execution
- retry limits
- cooldowns
- governance
- human approval
- execution state transitions
- ambiguous provider outcomes
- Copilot boundaries

---

## Technology

| Layer | Technology |
|---|---|
| Backend | Python / FastAPI |
| ML | scikit-learn |
| LLM | Tool-calling AI agent |
| Data | SQLite for prototype/demo |
| ORM / Persistence | Existing project data layer |
| API | REST |
| Webhooks | Razorpay |
| Security | HMAC SHA-256 |
| Analytics | Python attribution/experiment services |
| Frontend | Existing RecoverAI web application |
| Testing | Pytest |
| Version Control | Git / GitHub |

> The current implementation is a buildathon prototype designed around production-oriented safety principles. Production deployment would require infrastructure hardening such as a production database, distributed worker semantics, secrets management, observability, load testing, and deployment-specific controls.

---

## Repository Structure

The exact repository structure should be treated as authoritative in the codebase. Key logical modules include:

```text
ingestion/
    normalizer.py

models/
    recovery model artifact

policy/
    rules.py

agent/
    llm_agent.py
    copilot_engine.py

execution/
    idempotency.py

analytics/
    attribution.py
    experiments.py
```

---

## Running Locally

Use the project's existing environment and startup commands.

Typical development flow:

```bash
# install dependencies
pip install -r requirements.txt

# configure environment variables locally
# never commit secrets

# start the backend using the project's configured FastAPI entry point
# then open the frontend using the project's configured frontend command
```

Verify:

```text
Webhook ingestion
Recovery
Command Center
Policy Engine
Governance
Audit Trail
Simulator
Recovery Intelligence
Copilot
```

before submission.

---

## Buildathon Demo

The recommended five-minute demo follows one payment through the entire control plane:

```text
Payment failure
    ↓
Revenue at risk
    ↓
ML recovery prediction
    ↓
Policy decision
    ↓
Governance / approval
    ↓
Idempotent execution
    ↓
Recovery
    ↓
Audit trace
    ↓
Incremental impact
    ↓
Copilot investigation
```

See `DEMO_SCRIPT.md` for the exact walkthrough.

---

## Why RecoverAI

RecoverAI is not simply an AI model that predicts whether a payment will recover.

It is a controlled recovery system where:

- AI provides intelligence
- deterministic policies define boundaries
- governance controls financial authority
- idempotency protects execution
- audit trails provide accountability
- analytics measure economic impact
- Copilot provides an operational interface

**The goal is not maximum automation. The goal is safe, measurable automation.**
