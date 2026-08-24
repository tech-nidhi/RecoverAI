"""
Seed and Enrich RecoverAI Database to ensure EVERY Category, Action, and Outcome has realistic records.
"""

import sqlite3
import random
import uuid

def seed_database():
    db_path = "data/recover_ai.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    categories = [
        "payment_failure",
        "checkout_abandonment",
        "subscription_failure",
        "overdue_invoice"
    ]

    actions = ["RETRY", "PAYMENT_LINK", "REMINDER", "ESCALATE", "STOP"]
    outcomes = ["SUCCESS", "FAILED", "PENDING", "NO_ACTION"]

    # Category-specific parameters
    domain_data = {
        "payment_failure": {
            "cust_prefix": "cust_high_v",
            "amount_range": (35000, 280000),
            "reasons": ["INSUFFICIENT_FUNDS", "GATEWAY_TIMEOUT", "CARD_EXPIRED", "BANK_SYSTEM_OFFLINE", "UPI_TRANSIENT_FAILURE"],
            "archetype": "transient_high_value"
        },
        "checkout_abandonment": {
            "cust_prefix": "cust_checkout",
            "amount_range": (4500, 65000),
            "reasons": ["CHECKOUT_SESSION_EXPIRED", "PAYMENT_WINDOW_CLOSED", "CART_ABANDONED_AT_OTP", "DROPPED_AFTER_DISCOUNT"],
            "archetype": "checkout_abandonment"
        },
        "subscription_failure": {
            "cust_prefix": "cust_sub",
            "amount_range": (2499, 29999),
            "reasons": ["RECURRING_MANDATE_EXPIRED", "AUTO_DEBIT_FAILED", "CARD_MAX_LIMIT_EXCEEDED", "SAAS_RENEWAL_DECLINED"],
            "archetype": "subscription_dunning"
        },
        "overdue_invoice": {
            "cust_prefix": "acct_enterprise",
            "amount_range": (82000, 1250000),
            "reasons": ["INVOICE_31_DAYS_OVERDUE", "PAYMENT_TERMS_EXCEEDED", "NET30_WINDOW_EXPIRED", "ENTERPRISE_APPROVAL_DELAY"],
            "archetype": "overdue_receivables"
        }
    }

    new_records = []
    
    # Generate balanced records for EVERY category x action x outcome combination
    for cat in categories:
        info = domain_data[cat]
        for act in actions:
            for out in outcomes:
                # Align action and outcome policy consistency
                actual_out = "NO_ACTION" if act == "STOP" else out
                actual_act = "STOP" if out == "NO_ACTION" else act

                for i in range(5):
                    event_id = f"evt_{cat[:3]}_{actual_act[:2]}_{actual_out[:2]}_{uuid.uuid4().hex[:6]}"
                    cust_num = random.randint(1000, 9999)
                    customer_id = f"{info['cust_prefix']}_{cust_num}"
                    amount = round(random.uniform(*info["amount_range"]), 2)
                    
                    if actual_act == "STOP":
                        prob = round(random.uniform(0.05, 0.22), 4)
                    elif actual_act == "ESCALATE":
                        prob = round(random.uniform(0.35, 0.72), 4)
                    elif actual_act == "PAYMENT_LINK":
                        prob = round(random.uniform(0.65, 0.96), 4)
                    elif actual_act == "RETRY":
                        prob = round(random.uniform(0.55, 0.92), 4)
                    else:
                        prob = round(random.uniform(0.40, 0.85), 4)

                    reason = random.choice(info["reasons"])
                    attempts = random.randint(1, 4)
                    days_since = round(random.uniform(0.1, 7.0), 1)

                    total_past = random.randint(3, 25)
                    past_succ = random.randint(1, total_past)
                    past_rate = round(past_succ / total_past, 4)

                    if actual_out == "SUCCESS":
                        recovered = round(amount * random.uniform(0.92, 1.0), 2)
                        decision = "APPROVED: high_value_recovery"
                    elif actual_out == "NO_ACTION":
                        recovered = 0.0
                        decision = "BLOCKED: rule_1_stop_low_probability"
                    else:
                        recovered = 0.0
                        decision = "APPROVED: standard_intervention"

                    reasoning = f"Evaluated event for customer {customer_id}. Amount ₹{amount:,.2f} with recovery probability {prob*100:.1f}%. Action {actual_act} executed."

                    new_records.append((
                        event_id, cat, "2026-08-24T11:00:00Z", amount, customer_id, reason,
                        attempts, days_since, f"Summary for {customer_id}",
                        total_past, past_succ, past_rate,
                        info["archetype"], 1 if actual_out == "SUCCESS" else 0, prob, actual_act, decision,
                        actual_act, actual_out, recovered, reasoning
                    ))

    cursor.executemany("""
        INSERT OR REPLACE INTO revenue_events (
            event_id, event_type, timestamp, amount, customer_id, failure_reason,
            attempt_count, days_since_last_attempt, customer_history_summary,
            total_past_payments, past_successful_payments, past_recovery_rate,
            archetype, did_recover, recovery_probability, recommended_action, policy_decision,
            executed_action, outcome, revenue_recovered, reasoning_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, new_records)

    conn.commit()
    
    # Print statistics
    print(f"✓ Inserted/Updated {len(new_records)} balanced revenue events.")
    
    print("\n--- NEW EVENT TYPE COUNTS ---")
    cursor.execute("SELECT event_type, COUNT(*) FROM revenue_events GROUP BY event_type;")
    for r in cursor.fetchall():
        print(f"  {r[0]}: {r[1]} cases")

    print("\n--- NEW EXECUTED ACTION COUNTS ---")
    cursor.execute("SELECT executed_action, COUNT(*) FROM revenue_events GROUP BY executed_action;")
    for r in cursor.fetchall():
        print(f"  {r[0]}: {r[1]} cases")

    print("\n--- NEW OUTCOME COUNTS ---")
    cursor.execute("SELECT outcome, COUNT(*) FROM revenue_events GROUP BY outcome;")
    for r in cursor.fetchall():
        print(f"  {r[0]}: {r[1]} cases")

    conn.close()

if __name__ == "__main__":
    seed_database()
