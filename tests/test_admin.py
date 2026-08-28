import pytest

@pytest.mark.asyncio
async def test_admin_doctor_onboarding_and_verification(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Admin creates doctor account
    create_doc_payload = {
        "name": "Dr. Farzana Yasmin",
        "phone": "01755667788",
        "email": "dr.farzana@meditouch.com",
        "password": "DoctorSecret123!",
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
