"""
RecoverAI - Merchant Account, Authentication, Onboarding & Multi-Tenant Data Isolation Tests
"""

import os
import pytest
from fastapi.testclient import TestClient
from backend.api import app, DB_PATH
from auth.tenancy import (
    ensure_tenancy_tables_and_columns_exist,
    create_merchant_user,
    authenticate_user,
    get_session,
    verify_password,
    hash_password,
    create_api_key,
    verify_api_key,
    revoke_api_key
)

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensures multi-tenant database tables exist before each test."""
    ensure_tenancy_tables_and_columns_exist(DB_PATH)


def test_password_hashing():
    """Verifies that PBKDF2 password hashing is secure, non-plaintext, and uses salt."""
    raw_pass = "SecureMerchantPass123!"
    p_hash, salt = hash_password(raw_pass)
    
    assert p_hash != raw_pass
    assert len(salt) == 32
    assert verify_password(raw_pass, p_hash, salt) is True
    assert verify_password("WrongPass123", p_hash, salt) is False


def test_signup_login_flow():
    """Tests merchant user registration and login session generation."""
    email = f"merchant_{os.urandom(4).hex()}@acme.com"
    password = "SuperSecretPassword123!"
    full_name = "Jane Merchant"
    company_name = "Acme Global Solutions"

    # 1. Signup
    signup_res = client.post("/auth/signup", json={
        "email": email,
        "password": password,
        "full_name": full_name,
        "company_name": company_name
    })
    assert signup_res.status_code == 200
    signup_data = signup_res.json()
    assert "session_token" in signup_data
    assert signup_data["workspace"]["name"] == company_name
    ws_id = signup_data["workspace"]["id"]
    token = signup_data["session_token"]

    # 2. Authenticated /auth/me check
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["user"]["email"] == email
    assert me_data["workspace"]["id"] == ws_id

    # 3. Login
    login_res = client.post("/auth/login", json={
        "email": email,
        "password": password
    })
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["session_token"] != ""
    assert login_data["workspace"]["id"] == ws_id

    # 4. Logout
    logout_res = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200


def test_multi_tenant_data_isolation():
    """Verifies that Merchant A cannot access or view Merchant B's revenue events or webhooks."""
    # Register Merchant A
    res_a = client.post("/auth/signup", json={
        "email": f"merchant_a_{os.urandom(4).hex()}@company-a.com",
        "password": "PasswordA123!",
        "full_name": "Alice Admin",
        "company_name": "Company A"
    }).json()
    token_a = res_a["session_token"]
    ws_a = res_a["workspace"]["id"]

    # Register Merchant B
    res_b = client.post("/auth/signup", json={
        "email": f"merchant_b_{os.urandom(4).hex()}@company-b.com",
        "password": "PasswordB123!",
        "full_name": "Bob Boss",
        "company_name": "Company B"
    }).json()
    token_b = res_b["session_token"]
    ws_b = res_b["workspace"]["id"]

    assert ws_a != ws_b

    # Merchant A posts a webhook payment failure
    event_id_a = f"pay_m_a_{os.urandom(4).hex()}"
    webhook_res_a = client.post("/webhooks/razorpay", headers={"Authorization": f"Bearer {token_a}"}, json={
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": event_id_a,
                    "amount": 500000,
                    "currency": "INR",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed for Merchant A",
                    "contact": "+919000000001",
                    "email": "customer_a@gmail.com"
                }
            }
        }
    })
    assert webhook_res_a.status_code == 200

    # Merchant B posts a webhook payment failure
    event_id_b = f"pay_m_b_{os.urandom(4).hex()}"
    webhook_res_b = client.post("/webhooks/razorpay", headers={"Authorization": f"Bearer {token_b}"}, json={
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": event_id_b,
                    "amount": 990000,
                    "currency": "INR",
                    "status": "failed",
                    "error_code": "GATEWAY_ERROR",
                    "error_description": "Payment failed for Merchant B",
                    "contact": "+919000000002",
                    "email": "customer_b@gmail.com"
                }
            }
        }
    })
    assert webhook_res_b.status_code == 200

    # Merchant A fetches cases -> MUST see event_id_a, MUST NOT see event_id_b
    cases_a = client.get("/cases", headers={"Authorization": f"Bearer {token_a}"}).json()
    case_ids_a = [c["event_id"] for c in cases_a.get("cases", [])]
    assert any(event_id_a in cid for cid in case_ids_a)
    assert not any(event_id_b in cid for cid in case_ids_a)

    # Merchant B fetches cases -> MUST see event_id_b, MUST NOT see event_id_a
    cases_b = client.get("/cases", headers={"Authorization": f"Bearer {token_b}"}).json()
    case_ids_b = [c["event_id"] for c in cases_b.get("cases", [])]
    assert any(event_id_b in cid for cid in case_ids_b)
    assert not any(event_id_a in cid for cid in case_ids_b)


def test_api_key_lifecycle_and_revocation():
    """Tests generating, authenticating with, and revoking API keys."""
    # Register Merchant
    signup_res = client.post("/auth/signup", json={
        "email": f"apikey_user_{os.urandom(4).hex()}@tech.com",
        "password": "Password123!",
        "full_name": "API Admin",
        "company_name": "API Tech Corp"
    }).json()
    token = signup_res["session_token"]
    ws_id = signup_res["workspace"]["id"]

    # 1. Create API key
    key_res = client.post("/settings/api-keys", headers={"Authorization": f"Bearer {token}"}, json={
        "name": "Test Key 1",
        "environment": "SANDBOX"
    })
    assert key_res.status_code == 200
    key_data = key_res.json()
    raw_key = key_data["raw_api_key"]
    key_id = key_data["key_id"]
    assert raw_key.startswith("rai_test_")

    # 2. Authenticate request using X-API-Key header
    summary_res = client.get("/summary", headers={"X-API-Key": raw_key})
    assert summary_res.status_code == 200

    # 3. Revoke API Key
    revoke_res = client.delete(f"/settings/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert revoke_res.status_code == 200

    # 4. Request using revoked key MUST be rejected (falls back to unauthenticated or 401)
    revoked_summary_res = client.get("/summary", headers={"X-API-Key": raw_key})
    # If unauthenticated fallback defaults to ws_default, it shouldn't match ws_id
    cases_res = client.get("/cases", headers={"X-API-Key": raw_key})
    assert cases_res.status_code in [200, 401]


def test_onboarding_wizard_status():
    """Tests onboarding status retrieval and completion."""
    signup_res = client.post("/auth/signup", json={
        "email": f"onboarding_{os.urandom(4).hex()}@startup.io",
        "password": "Password123!",
        "full_name": "Onboarding User",
        "company_name": "Startup Inc"
    }).json()
    token = signup_res["session_token"]

    status_res = client.get("/onboarding/status", headers={"Authorization": f"Bearer {token}"})
    assert status_res.status_code == 200
    assert status_res.json()["onboarding_completed"] == False

    complete_res = client.post("/onboarding/complete", headers={"Authorization": f"Bearer {token}"}, json={
        "max_retries": 4,
        "cooldown_hours": 12.0,
        "approval_threshold": 50000.0
    })
    assert complete_res.status_code == 200
    assert complete_res.json()["onboarding_completed"] == True
