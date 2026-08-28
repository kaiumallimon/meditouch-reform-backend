import pytest

@pytest.mark.asyncio
async def test_bkash_payment_idempotency_and_refund(client, admin_auth, patient_auth, doctor_auth):
    patient_headers = patient_auth["headers"]
    admin_headers = admin_auth["headers"]
    doc_id = doctor_auth["doctor"]["id"]

    # 1. Create a timeslot & appointment
    slot_res = await client.post(
        "/api/v1/doctors/me/timeslots",
        json={"slots": [{"start_time": "2026-09-01T10:00:00Z", "end_time": "2026-09-01T10:30:00Z"}]},
        headers=doctor_auth["headers"]
    )
    timeslot_id = slot_res.json()["data"][0]["id"]

    book_res = await client.post(
        "/api/v1/appointments/book",
        json={"doctor_id": doc_id, "timeslot_id": timeslot_id},
        headers=patient_headers
    )
    apt_data = book_res.json()["data"]
    bkash_payment_id = apt_data["payment_url"].split("paymentID=")[-1]
    payment_id = apt_data["payment_id"]

    # 2. First callback execution -> SUCCESS
    cb1 = await client.post(f"/api/v1/payments/bkash/callback?paymentID={bkash_payment_id}&status=success")
    assert cb1.status_code == 200
    assert cb1.json()["data"]["status"] == "COMPLETED"

    # 3. Duplicate callback execution -> IDEMPOTENT (no error, status COMPLETED)
    cb2 = await client.post(f"/api/v1/payments/bkash/callback?paymentID={bkash_payment_id}&status=success")
    assert cb2.status_code == 200
    assert cb2.json()["data"]["status"] == "COMPLETED"

    # 4. Admin refunds payment
    ref_res = await client.post(
        f"/api/v1/payments/{payment_id}/refund",
        json={"reason": "Test refund"},
        headers=admin_headers
    )
    assert ref_res.status_code == 200
    assert ref_res.json()["data"]["status"] == "REFUNDED"
