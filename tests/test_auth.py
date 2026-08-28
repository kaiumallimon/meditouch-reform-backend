import pytest

@pytest.mark.asyncio
async def test_register_and_login_patient(client):
    # 1. Register
    reg_payload = {
        "name": "Arif Ahmed",
        "phone": "01711223344",
        "email": "arif@test.com",
        "password": "Password123!",
        "gender": "male",
        "address": "Dhanmondi, Dhaka"
    }
    res = await client.post("/api/v1/auth/register", json=reg_payload)
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["name"] == "Arif Ahmed"
    assert data["role"] == "USER"
    assert "access_token" in data
    assert "refresh_token" in data

    # 2. Duplicate registration fails
    dup_res = await client.post("/api/v1/auth/register", json=reg_payload)
    assert dup_res.status_code == 409

    # 3. Login with phone
    login_payload = {
        "identifier": "01711223344",
        "password": "Password123!"
    }
    login_res = await client.post("/api/v1/auth/login", json=login_payload)
    assert login_res.status_code == 200
    assert login_res.json()["data"]["role"] == "USER"

    # 4. Login with invalid password fails
    bad_login = await client.post("/api/v1/auth/login", json={"identifier": "01711223344", "password": "WrongPassword"})
    assert bad_login.status_code == 401

@pytest.mark.asyncio
async def test_refresh_token_rotation(client, patient_auth):
    refresh_payload = {
        "refresh_token": patient_auth["token"] # We'll create refresh token
    }
    # Login to get fresh tokens
    login_res = await client.post("/api/v1/auth/login", json={
        "identifier": patient_auth["user"]["phone"],
        "password": "PatientPass123!"
    })
    tokens = login_res.json()["data"]

    ref_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref_res.status_code == 200
    new_tokens = ref_res.json()["data"]
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens

@pytest.mark.asyncio
async def test_get_current_user_and_change_password(client, patient_auth):
    headers = patient_auth["headers"]

    # 1. Get Me
    me_res = await client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["data"]["phone"] == patient_auth["user"]["phone"]

    # 2. Change password
    pwd_payload = {
        "current_password": "PatientPass123!",
        "new_password": "NewSecretPassword99!"
    }
    chg_res = await client.post("/api/v1/auth/change-password", json=pwd_payload, headers=headers)
    assert chg_res.status_code == 200

    # 3. Old password should fail
    old_login = await client.post("/api/v1/auth/login", json={
        "identifier": patient_auth["user"]["phone"],
        "password": "PatientPass123!"
    })
    assert old_login.status_code == 401

    # 4. New password succeeds
    new_login = await client.post("/api/v1/auth/login", json={
        "identifier": patient_auth["user"]["phone"],
        "password": "NewSecretPassword99!"
    })
    assert new_login.status_code == 200
