import pytest
from datetime import datetime, timezone, timedelta
from app.common.enums import AppointmentStatus

@pytest.mark.asyncio
async def test_consultation_video_token_and_completion(client, mock_db, doctor_auth, patient_auth):
    doc_headers = doctor_auth["headers"]
    patient_headers = patient_auth["headers"]
    doc_id = doctor_auth["doctor"]["id"]
    patient_id = patient_auth["user"]["id"]

    # 1. Create a confirmed appointment currently in joinable window (now to now+30m)
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=2)
    end_time = now + timedelta(minutes=28)
    apt_id = "test-consultation-apt-001"

    apt_doc = {
        "id": apt_id,
        "patient_id": patient_id,
        "patient_name": patient_auth["user"]["name"],
        "patient_phone": patient_auth["user"]["phone"],
        "doctor_id": doc_id,
        "doctor_name": doctor_auth["doctor"]["name"],
        "timeslot_id": "slot-001",
        "start_time": start_time,
        "end_time": end_time,
        "doctor_fee": 500.0,
        "platform_fee": 50.0,
        "total_amount": 550.0,
        "status": AppointmentStatus.CONFIRMED.value,
        "created_at": now
    }
    await mock_db.appointments.insert_one(apt_doc)

    # 2. Patient requests ZEGOCLOUD video room token
    p_token_res = await client.post(f"/api/v1/consultations/{apt_id}/token", headers=patient_headers)
    assert p_token_res.status_code == 200
    p_data = p_token_res.json()["data"]
    assert p_data["zego_token"].startswith("04")
    assert p_data["room_id"] == f"meditouch_{apt_id}"
    assert p_data["user_id"] == patient_id

    # 3. Doctor requests ZEGOCLOUD video room token
    d_token_res = await client.post(f"/api/v1/consultations/{apt_id}/token", headers=doc_headers)
    assert d_token_res.status_code == 200
    d_data = d_token_res.json()["data"]
    assert d_data["zego_token"].startswith("04")

    # 4. Doctor completes consultation with clinical notes & prescription
    complete_payload = {
        "diagnosis": "Acute Bronchitis & Allergic Rhinitis",
        "clinical_notes": "Chest clear with slight wheezing. Blood pressure normal.",
        "prescriptions": [
            {
                "medicine_name": "Monas 10",
                "dosage": "10 mg",
                "frequency": "0+0+1",
                "duration_days": 14,
                "instructions": "Take after dinner"
            },
            {
                "medicine_name": "Alatrol",
                "dosage": "10 mg",
                "frequency": "0+0+1",
                "duration_days": 7,
                "instructions": "Take at night for itching/sneezing"
            }
        ],
        "follow_up_date": (now + timedelta(days=14)).strftime("%Y-%m-%d"),
        "advice": "Drink warm water, avoid cold dust exposure."
    }
    comp_res = await client.post(f"/api/v1/consultations/{apt_id}/complete", json=complete_payload, headers=doc_headers)
    assert comp_res.status_code == 200
    comp_data = comp_res.json()["data"]
    assert comp_data["diagnosis"] == "Acute Bronchitis & Allergic Rhinitis"
    assert len(comp_data["prescriptions"]) == 2

    # 5. Patient views completed prescription/medical record
    record_res = await client.get(f"/api/v1/consultations/{apt_id}", headers=patient_headers)
    assert record_res.status_code == 200
    assert record_res.json()["data"]["advice"] == "Drink warm water, avoid cold dust exposure."
