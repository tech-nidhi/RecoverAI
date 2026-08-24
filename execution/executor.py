"""
Action Executor & Idempotency Engine for RecoverAI (Phase 4).

Dispatches actions strictly based on Phase 3 approved event.executed_action (or final_action).
Contains ZERO decision logic or rule re-evaluation.
Includes an idempotency check to skip duplicate executions if outcome is already populated.
"""

from execution.razorpay_client import retry_payment, create_payment_link, send_reminder, GatewayResponse
from schema.event_schema import RevenueEvent


def execute_action(event: RevenueEvent) -> RevenueEvent:
    """
    Executes the approved action for a RevenueEvent and populates outcome & revenue_recovered.

    Args:
        event: RevenueEvent model instance containing Phase 3 executed_action.

    Returns:
        RevenueEvent: Updated event model with outcome and revenue_recovered fields.
    """
    # -------------------------------------------------------------------------
    # IDEMPOTENCY CHECK: Skip execution if outcome is already populated!
    # -------------------------------------------------------------------------
    if event.outcome is not None and str(event.outcome).strip() != "":
        # Already executed, return unchanged for idempotency
        return event

    action = (event.executed_action or event.recommended_action or "STOP").upper().strip()

    if action == "RETRY":
        resp: GatewayResponse = retry_payment(event)
        event.outcome = resp.status
        event.revenue_recovered = event.amount if resp.success else 0.0

    elif action == "PAYMENT_LINK":
        resp: GatewayResponse = create_payment_link(event)
        event.outcome = resp.status
        event.revenue_recovered = event.amount if resp.success else 0.0

    elif action == "REMINDER":
        resp: GatewayResponse = send_reminder(event)
        event.outcome = resp.status
        event.revenue_recovered = event.amount if resp.success else 0.0

    elif action == "ESCALATE":
        # Log escalation for human follow-up — no API call required
        event.outcome = "PENDING"
        event.revenue_recovered = 0.0

    elif action == "STOP":
        # Log stop — no gateway API call required, recovery halted
        event.outcome = "NO_ACTION"
        event.revenue_recovered = 0.0

    else:
        # Fallback for unknown actions
        event.outcome = "NO_ACTION"
        event.revenue_recovered = 0.0

    return event
