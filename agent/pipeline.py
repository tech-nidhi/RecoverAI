"""
End-to-End Event Processing Pipeline for RecoverAI (Phase 3).

Coordinates the LLM Reasoning Agent and Policy Engine for a single RevenueEvent:
1. Calls decide_action(event) to get LLM recommendation & reasoning.
2. Calls evaluate_policy(event, recommended_action, rules) to enforce hard guardrails.
3. Updates event fields (recommended_action, policy_decision, executed_action, reasoning_text).
4. Logs full audit record to SQLite 'decisions' table.
"""

from typing import Dict, Optional, Any

from agent.decision_log import log_decision
from agent.llm_agent import decide_action, AgentDecision
from policy.policy_engine import evaluate_policy, PolicyEvaluationResult
from schema.event_schema import RevenueEvent


def process_event(
    event: RevenueEvent,
    rules: Optional[Dict[str, Any]] = None,
    db_path: str = "data/recover_ai.db",
    anthropic_api_key: Optional[str] = None
) -> RevenueEvent:
    """
    Processes a single RevenueEvent through the AI Agent and Policy Engine.

    Args:
        event: RevenueEvent model instance to process.
        rules: Optional policy rules dictionary. If None, loads from policy/rules.yaml.
        db_path: Path to SQLite DB for logging decision audit records.
        anthropic_api_key: Optional API key for Claude API.

    Returns:
        RevenueEvent: Updated event object with Phase 3 fields populated.
    """
    # 1. LLM Reasoning Agent Step: Propose recommendation & reasoning
    agent_decision: AgentDecision = decide_action(event, anthropic_api_key=anthropic_api_key)

    # 2. Deterministic Policy Engine Step: Enforce hard guardrails
    policy_result: PolicyEvaluationResult = evaluate_policy(
        event=event,
        recommended_action=agent_decision.recommended_action,
        rules=rules
    )

    # 3. Update RevenueEvent fields
    event.recommended_action = agent_decision.recommended_action
    
    if policy_result.approved:
        event.policy_decision = "APPROVED"
    else:
        event.policy_decision = f"BLOCKED: {policy_result.blocking_rule}"

    event.executed_action = policy_result.final_action
    event.reasoning_text = agent_decision.reasoning_text

    # 4. Log full decision audit record to SQLite
    try:
        log_decision(
            event=event,
            agent_decision=agent_decision,
            policy_result=policy_result,
            db_path=db_path
        )
    except Exception as e:
        print(f"[Warning] Failed to log decision to SQLite ({e})")

    return event
