import pytest

@pytest.mark.asyncio
async def test_admin_doctor_onboarding_and_verification(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Admin creates doctor account (without initial password - auto-generated passphrase & emailed)
    create_doc_payload = {
        "name": "Dr. Farzana Yasmin",
        "phone": "01755667788",
        "email": "dr.farzana@meditouch.com",
        "bmdc_reg_number": "A-99881",
        "specialties": ["Gynecology", "Obstetrics"],
        "qualifications": ["MBBS", "FCPS (Gynae)"],
        "experience_years": 8,
        "consultation_fee": 600.0,
        "bio": "Specialist in maternal and women's health.",
        "verification_documents": [
            {
                "document_type": "BMDC_CERTIFICATE",
                "document_url": "https://storage.meditouch.com/docs/bmdc_99881.pdf"
            }
        ]
    }
    doc_res = await client.post("/api/v1/admin/doctors", json=create_doc_payload, headers=headers)
    assert doc_res.status_code == 201
    doc_data = doc_res.json()["data"]
    assert doc_data["bmdc_reg_number"] == "A-99881"
    assert doc_data["is_verified"] is False
    assert doc_data["is_active"] is False

    doc_id = doc_data["id"]

    # 2. Admin reviews and approves verification
    verify_res = await client.post(
        f"/api/v1/admin/doctors/{doc_id}/verify",
        json={"status": "VERIFIED"},
        headers=headers
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["data"]["is_verified"] is True
    assert verify_res.json()["data"]["is_active"] is True

    # 3. Admin views dashboard stats
    stats_res = await client.get("/api/v1/admin/dashboard/stats", headers=headers)
    assert stats_res.status_code == 200
    assert stats_res.json()["data"]["total_doctors"] >= 1

    # 4. Admin views audit logs
    audit_res = await client.get("/api/v1/admin/audit-logs", headers=headers)
    assert audit_res.status_code == 200
    assert len(audit_res.json()["data"]["items"]) >= 1

@pytest.mark.asyncio
async def test_non_admin_forbidden(client, patient_auth):
    # Patient trying to access admin endpoints gets 403
    res = await client.get("/api/v1/admin/dashboard/stats", headers=patient_auth["headers"])
    assert res.status_code == 403

@pytest.mark.asyncio
async def test_audit_logs_recorded_for_sensitive_actions(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Admin creates a doctor to trigger an audit event
    create_doc_payload = {
        "name": "Dr. Audit Test",
        "phone": "01799881122",
        "email": "dr.audit@meditouch.com",
        "password": "DoctorSecret123!",
        "bmdc_reg_number": "A-77665",
        "specialties": ["Cardiology"],
        "qualifications": ["MBBS"],
        "experience_years": 5,
        "consultation_fee": 500.0
    }
    await client.post("/api/v1/admin/doctors", json=create_doc_payload, headers=headers)

    # 2. Retrieve all audit logs recorded
    audit_res = await client.get("/api/v1/admin/audit-logs", headers=headers)
    assert audit_res.status_code == 200
    logs = audit_res.json()["data"]["items"]
    actions = [log["action"] for log in logs]
    
    # Verify that DOCTOR_CREATED action exists in audit logs
    assert "DOCTOR_CREATED" in actions

@pytest.mark.asyncio
async def test_doctor_passphrase_and_welcome_email_dispatch(client, admin_auth):
    headers = admin_auth["headers"]
    from app.common.passphrase import generate_readable_passphrase
    from app.integrations.smtp import render_doctor_welcome_email

    # Verify passphrase generator format
    passphrase = generate_readable_passphrase()
    assert len(passphrase) >= 12
    assert "-" in passphrase

    # Verify email rendering contains both plain text and HTML
    plain, html = render_doctor_welcome_email(
        name="Farzana Yasmin",
        phone="01711223344",
        email="dr.farzana@meditouch.com",
        passphrase=passphrase
    )
    assert "Farzana Yasmin" in plain
    assert passphrase in plain
    assert "Farzana Yasmin" in html
    assert passphrase in html
    assert "#5B15FC" in html or "#5b15fc" in html.lower()

    # Admin creates doctor without password
    res = await client.post(
        "/api/v1/admin/doctors",
        json={
            "name": "Dr. Auto Passphrase",
            "phone": "01788776655",
            "email": "dr.autopass@meditouch.com",
            "bmdc_reg_number": "A-12399",
            "specialties": ["Pediatrics"],
            "qualifications": ["MBBS", "DCH"],
            "experience_years": 4,
            "consultation_fee": 400.0
        },
        headers=headers
    )
    assert res.status_code == 201
    assert res.json()["data"]["email"] == "dr.autopass@meditouch.com"

@pytest.mark.asyncio
async def test_admin_update_and_soft_delete_doctor(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Create a doctor
    create_res = await client.post(
        "/api/v1/admin/doctors",
        json={
            "name": "Dr. Kamal Uddin",
            "phone": "01733445566",
            "email": "dr.kamal@meditouch.com",
            "bmdc_reg_number": "A-55443",
            "specialties": ["Orthopedics"],
            "qualifications": ["MBBS", "MS (Ortho)"],
            "experience_years": 10,
            "consultation_fee": 700.0,
            "bio": "Experienced orthopedic surgeon."
        },
        headers=headers
    )
    assert create_res.status_code == 201
    doc_id = create_res.json()["data"]["id"]

    # 2. Update doctor details (consultation fee, experience, name)
    update_res = await client.patch(
        f"/api/v1/admin/doctors/{doc_id}",
        json={
            "name": "Dr. Kamal Uddin Chowdhury",
            "consultation_fee": 850.0,
            "experience_years": 12,
            "bio": "Senior Orthopedic Surgeon"
        },
        headers=headers
    )
    assert update_res.status_code == 200
    updated = update_res.json()["data"]
    assert updated["name"] == "Dr. Kamal Uddin Chowdhury"
    assert updated["consultation_fee"] == 850.0
    assert updated["experience_years"] == 12

    # 3. Soft delete doctor
    del_res = await client.delete(f"/api/v1/admin/doctors/{doc_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["data"]["deleted"] is True

    # 4. Ensure doctor is excluded from general admin list
    list_res = await client.get("/api/v1/admin/doctors", headers=headers)
    assert list_res.status_code == 200
    listed_ids = [d["id"] for d in list_res.json()["data"]["items"]]
    assert doc_id not in listed_ids

@pytest.mark.asyncio
async def test_admin_user_crud_recovery_and_stats(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Admin creates a new sub-admin account
    create_payload = {
        "name": "Super Moderator",
        "phone": "01811223399",
        "email": "mod@meditouch.com",
        "role": "ADMIN",
        "avatar_url": "https://res.cloudinary.com/m2nxsbff/image/upload/v1/mod.png"
    }
    create_res = await client.post("/api/v1/admin/users", json=create_payload, headers=headers)
    assert create_res.status_code == 201
    user_data = create_res.json()["data"]
    assert user_data["name"] == "Super Moderator"
    assert user_data["role"] == "ADMIN"
    assert user_data["is_active"] is True
    user_id = user_data["id"]

    # 2. Get user stats
    stats_res = await client.get("/api/v1/admin/users/stats", headers=headers)
    assert stats_res.status_code == 200
    stats = stats_res.json()["data"]
    assert stats["total_users"] >= 1
    assert stats["total_admins"] >= 1
    assert "total_regular_users" in stats

    # 3. List all users with filtering
    list_res = await client.get("/api/v1/admin/users?role=ADMIN", headers=headers)
    assert list_res.status_code == 200
    items = list_res.json()["data"]["items"]
    assert any(u["id"] == user_id for u in items)

    # 4. Update user account (deactivate & update name)
    update_res = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"name": "Moderator Updated", "is_active": False},
        headers=headers
    )
    assert update_res.status_code == 200
    assert update_res.json()["data"]["name"] == "Moderator Updated"
    assert update_res.json()["data"]["is_active"] is False

    # 5. Send password recovery email / generate passphrase
    recover_res = await client.post(f"/api/v1/admin/users/{user_id}/recover-password", headers=headers)
    assert recover_res.status_code == 200
    assert "recovery" in recover_res.json()["message"].lower()

    # 6. Soft delete user
    del_res = await client.delete(f"/api/v1/admin/users/{user_id}", headers=headers)
    assert del_res.status_code == 200

    # 7. Verify soft deleted user is not in active users list
    list_after_res = await client.get("/api/v1/admin/users", headers=headers)
    assert list_after_res.status_code == 200
    active_ids = [u["id"] for u in list_after_res.json()["data"]["items"]]
    assert user_id not in active_ids

    # 8. Admin cannot self-deactivate their own logged-in account
    admin_self_id = admin_auth["user"]["id"]
    self_deact_res = await client.patch(
        f"/api/v1/admin/users/{admin_self_id}",
        json={"is_active": False},
        headers=headers
    )
    assert self_deact_res.status_code == 400
    assert "cannot deactivate your own" in self_deact_res.json()["message"]

    # 9. Admin cannot self-delete their own logged-in account
    self_del_res = await client.delete(f"/api/v1/admin/users/{admin_self_id}", headers=headers)
    assert self_del_res.status_code == 400
    assert "cannot delete your own" in self_del_res.json()["message"]

    # 10. Re-create a new user with the EXACT SAME phone and email after soft delete
    recreate_res = await client.post(
        "/api/v1/admin/users",
        json={
            "name": "Recreated User Account",
            "phone": "01811223399",
            "email": "mod@meditouch.com",
            "role": "ADMIN",
            "is_active": True
        },
        headers=headers
    )
    assert recreate_res.status_code == 201
    new_user_data = recreate_res.json()["data"]
    assert new_user_data["phone"] == "+8801811223399"
    assert new_user_data["email"] == "mod@meditouch.com"
    assert new_user_data["id"] != user_id






