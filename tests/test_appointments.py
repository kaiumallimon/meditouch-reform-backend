import pytest
from datetime import datetime, timezone, timedelta

@pytest.mark.asyncio
async def test_appointment_booking_and_concurrency(client, doctor_auth, patient_auth):
    doc_headers = doctor_auth["headers"]
    patient_headers = patient_auth["headers"]
    doc_id = doctor_auth["doctor"]["id"]

    # 1. Doctor creates a timeslot
    now = datetime.now(timezone.utc)
    slot_start = now + timedelta(days=2, hours=14)
    slot_end = slot_start + timedelta(minutes=30)
    slots_res = await client.post(
        "/api/v1/doctors/me/timeslots",
        json={"slots": [{"start_time": slot_start.isoformat(), "end_time": slot_end.isoformat()}]},
        headers=doc_headers
    )
    timeslot_id = slots_res.json()["data"][0]["id"]

    # 2. Check fee breakdown
    fee_res = await client.get(f"/api/v1/appointments/fee-breakdown/{doc_id}")
    assert fee_res.status_code == 200
    fee_data = fee_res.json()["data"]
    assert fee_data["doctor_fee"] == 500.0
    assert fee_data["platform_fee"] == 50.0
    assert fee_data["total_amount"] == 550.0

    # 3. Patient books appointment
    book_payload = {
        "doctor_id": doc_id,
        "timeslot_id": timeslot_id,
        "patient_notes": "Frequent chest tightness and headache",
        "symptoms": ["Chest pain", "Dizziness"]
    }
    book_res = await client.post("/api/v1/appointments/book", json=book_payload, headers=patient_headers)
    assert book_res.status_code == 201
    apt_data = book_res.json()["data"]
    assert apt_data["status"] == "PENDING_PAYMENT"
    assert apt_data["total_amount"] == 550.0
    assert "bkash" in apt_data["payment_url"].lower()

    # 4. CONCURRENCY: Second user tries to book the same timeslot -> returns 409 Conflict
    dup_res = await client.post("/api/v1/appointments/book", json=book_payload, headers=patient_headers)
    assert dup_res.status_code == 409

    # 5. Verify payment callback confirms appointment
    bkash_payment_id = apt_data["payment_url"].split("paymentID=")[-1]
    pay_res = await client.post(
        f"/api/v1/payments/bkash/callback?paymentID={bkash_payment_id}&status=success"
    )
    assert pay_res.status_code == 200
    assert pay_res.json()["data"]["status"] == "COMPLETED"

    # 6. Verify appointment is now CONFIRMED
    apt_id = apt_data["id"]
    get_apt_res = await client.get(f"/api/v1/appointments/{apt_id}", headers=patient_headers)
    assert get_apt_res.status_code == 200
    assert get_apt_res.json()["data"]["status"] == "CONFIRMED"

    # 7. Doctor views confirmed appointment
    doc_apts_res = await client.get("/api/v1/appointments/doctor-appointments", headers=doc_headers)
    assert doc_apts_res.status_code == 200
    assert len(doc_apts_res.json()["data"]["items"]) >= 1
