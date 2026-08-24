"""
LLM Reasoning Agent for RecoverAI (Phase 3).

Uses Anthropic Claude API (with structured output tool use) to analyze payment events
and recommend an optimal recovery action with natural language reasoning.
Includes an intelligent mock fallback for offline hackathon demonstrations and testing.
"""

import json
import os
from typing import Literal, Optional
from pydantic import BaseModel, Field

from schema.event_schema import RevenueEvent

# Allowed recommended actions
ActionType = Literal["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"]


class AgentDecision(BaseModel):
    """Structured response object returned by the LLM reasoning agent."""
    recommended_action: ActionType = Field(
        ...,
        description="Recommended recovery action: RETRY, PAYMENT_LINK, REMINDER, ESCALATE, or STOP."
    )
    reasoning_text: str = Field(
        ...,
        description="Concise 2-3 sentence explanation of the rationale behind the recommendation."
    )


# System prompt establishing role, boundaries, and reasoning instructions
SYSTEM_PROMPT = """You are RecoverAI's Senior Payments Revenue Recovery Agent.
Your job is to analyze failed or overdue payment events and recommend the single best recovery action.

Available Actions:
- RETRY: Trigger automated payment gateway retry (best for transient network or temporary balance issues).
- PAYMENT_LINK: Send an interactive 2FA/OTP payment link via SMS/Email (best for high-value transactions or card authentication drops).
- REMINDER: Send a gentle invoice or checkout abandonment reminder notice (best for overdue invoices or abandoned carts).
- ESCALATE: Escalate to a human customer success agent (best for high-risk or repeatedly failing accounts).
- STOP: Terminate recovery attempts (best when recovery probability is extremely low or retry caps reached).

CRITICAL BOUNDARIES:
- You ONLY provide recommendations and concise reasoning (2-3 sentences).
- You DO NOT execute transactions, modify databases, or dispatch notifications directly.
- Base your decision on transaction amount, failure reason, attempt count, past customer history, and ML recovery probability.
"""


def _build_event_prompt(event: RevenueEvent) -> str:
    """Formats event features into a clean structured prompt for the LLM."""
    h = event.customer_history_summary
    rec_prob_str = f"{event.recovery_probability * 100:.1f}%" if event.recovery_probability is not None else "Unknown"

    prompt = f"""Evaluate the following payment failure event:

Event Details:
- Event ID: {event.event_id}
- Event Type: {event.event_type}
- Amount: ₹{event.amount:,.2f} INR
- Failure Reason: {event.failure_reason or 'Unknown'}
- Attempt Count: {event.attempt_count}
- Days Since Last Attempt: {event.days_since_last_attempt:.1f} days

Customer Profile:
- Total Past Payments: {h.total_past_payments}
- Past Successful Payments: {h.past_successful_payments}
- Past Historical Recovery Rate: {h.past_recovery_rate * 100:.1f}%

ML Predictive Signal:
- ML Model Predicted Recovery Probability: {rec_prob_str}

Recommend the optimal action (RETRY, PAYMENT_LINK, REMINDER, ESCALATE, or STOP) and explain your reasoning in 2-3 concise sentences.
"""
    return prompt


def decide_action(
    event: RevenueEvent,
    anthropic_api_key: Optional[str] = None
) -> AgentDecision:
    """
    Invokes LLM agent to analyze payment event and return recommended action + reasoning text.

    Args:
        event: RevenueEvent Pydantic model instance containing event features.
        anthropic_api_key: Optional Anthropic API key. If None, checks os.environ['ANTHROPIC_API_KEY'].

    Returns:
        AgentDecision: Pydantic model with recommended_action and reasoning_text.
    """
    api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")

    # If Anthropic API key is provided and valid, call Claude API
    if api_key and not api_key.startswith("mock_"):
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            prompt_text = _build_event_prompt(event)

            # Tool definition for structured output
            decision_tool = {
                "name": "submit_recovery_recommendation",
                "description": "Submit the recommended recovery action and 2-3 sentence rationale.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "recommended_action": {
                            "type": "string",
                            "enum": ["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"],
                            "description": "The recommended recovery action."
                        },
                        "reasoning_text": {
                            "type": "string",
                            "description": "2-3 sentence explanation of the reasoning behind the recommendation."
                        }
                    },
                    "required": ["recommended_action", "reasoning_text"]
                }
            }

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=300,
                temperature=0.2,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt_text}],
                tools=[decision_tool],
                tool_choice={"type": "tool", "name": "submit_recovery_recommendation"}
            )

            # Extract tool response
            for content_block in response.content:
                if content_block.type == "tool_use" and content_block.name == "submit_recovery_recommendation":
                    tool_input = content_block.input
                    return AgentDecision(
                        recommended_action=tool_input["recommended_action"],
                        reasoning_text=tool_input["reasoning_text"]
                    )

        except Exception as e:
            print(f"[Warning] Anthropic API call failed ({e}). Falling back to heuristic reasoning assistant.")

    # -------------------------------------------------------------------------
    # HEURISTIC REASONING FALLBACK (For offline hackathon demo & test suites)
    # -------------------------------------------------------------------------
    return _heuristic_decide_action(event)


def _heuristic_decide_action(event: RevenueEvent) -> AgentDecision:
    """Heuristic reasoning assistant providing realistic recommendations & 2-3 sentence rationale."""
    prob = event.recovery_probability if event.recovery_probability is not None else 0.5
    amount = event.amount
    attempts = event.attempt_count
    event_type = event.event_type
    failure_reason = event.failure_reason or ""
    history = event.customer_history_summary

    if prob < 0.20:
        action = "STOP"
        reasoning = (
            f"The predicted recovery probability is extremely low ({prob*100:.1f}%), indicating high likelihood of permanent failure. "
            f"Given {attempts} prior failed attempt(s) and poor past payment performance, continuing automated attempts would incur unnecessary fees and annoy the customer. "
            f"We recommend halting all recovery efforts for this invoice."
        )
    elif amount >= 20000 and event_type in ["payment_failure", "subscription_failure"]:
        action = "PAYMENT_LINK"
        reasoning = (
            f"This is a high-value transaction of ₹{amount:,.2f} INR that requires customer-initiated 2FA authentication. "
            f"Automated gateway retries frequently fail for transactions of this scale due to bank security policies. "
            f"Sending a secure payment link directly to the customer provides a seamless authentication flow and yields optimal recovery."
        )
    elif event_type == "overdue_invoice" or failure_reason == "overdue":
        action = "REMINDER"
        reasoning = (
            f"The invoice of ₹{amount:,.2f} INR is overdue with {attempts} previous attempt(s). "
            f"The customer has a solid historical recovery rate of {history.past_recovery_rate*100:.1f}%, indicating willingness to pay once notified. "
            f"Sending a formal payment reminder notice is the most effective approach to prompt settlement."
        )
    elif event_type == "checkout_abandonment" or failure_reason == "abandoned":
        action = "REMINDER"
        reasoning = (
            f"The customer abandoned checkout for an order worth ₹{amount:,.2f} INR. "
            f"Since no transaction was submitted to the payment gateway, automated retries are inapplicable. "
            f"We recommend sending a targeted checkout reminder notice with an instant payment link."
        )
    elif attempts >= 3:
        action = "ESCALATE"
        reasoning = (
            f"Automated recovery has failed after {attempts} attempts for this transaction of ₹{amount:,.2f} INR. "
            f"With ML recovery probability estimated at {prob*100:.1f}%, automated retries have diminishing returns. "
            f"Escalating to a human customer success representative is recommended for personalized outreach."
        )
    else:
        action = "RETRY"
        reasoning = (
            f"The failure reason '{failure_reason}' appears transient with an estimated recovery probability of {prob*100:.1f}%. "
            f"The customer maintains a healthy historical success rate of {history.past_recovery_rate*100:.1f}% across {history.total_past_payments} past payments. "
            f"An automated payment gateway retry within standard cooldown limits is recommended."
        )

    return AgentDecision(recommended_action=action, reasoning_text=reasoning)
