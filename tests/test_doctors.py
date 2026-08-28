import pytest
from datetime import datetime, timezone, timedelta

@pytest.mark.asyncio
async def test_doctor_search_and_profile(client, doctor_auth):
    # 1. Search doctors
    res = await client.get("/api/v1/doctors?specialty=Cardiology")
    assert res.status_code == 200
    items = res.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["bmdc_reg_number"] == "A-12345"

    # 2. Get doctor by ID
    doc_id = doctor_auth["doctor"]["id"]
    detail_res = await client.get(f"/api/v1/doctors/{doc_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["data"]["name"] == "Dr. Rafiqul Islam"

@pytest.mark.asyncio
async def test_doctor_profile_update_and_timeslot_creation(client, doctor_auth):
    headers = doctor_auth["headers"]

    # 1. Update Profile (fee & bio)
    update_payload = {
        "consultation_fee": 650.0,
        "bio": "Updated bio with 12 years of clinical practice in cardiology.",
        "experience_years": 12
    }
    up_res = await client.put("/api/v1/doctors/me/profile", json=update_payload, headers=headers)
    assert up_res.status_code == 200
    assert up_res.json()["data"]["consultation_fee"] == 650.0

    # 2. Create Timeslots
    now = datetime.now(timezone.utc)
    slot1_start = now + timedelta(days=1, hours=10)
    slot1_end = slot1_start + timedelta(minutes=30)
    slot2_start = now + timedelta(days=1, hours=11)
    slot2_end = slot2_start + timedelta(minutes=30)

    slots_payload = {
        "slots": [
            {"start_time": slot1_start.isoformat(), "end_time": slot1_end.isoformat()},
            {"start_time": slot2_start.isoformat(), "end_time": slot2_end.isoformat()}
        ]
    }
    create_res = await client.post("/api/v1/doctors/me/timeslots", json=slots_payload, headers=headers)
    assert create_res.status_code == 201
    created_slots = create_res.json()["data"]
    assert len(created_slots) == 2

    # 3. Public views available timeslots
    doc_id = doctor_auth["doctor"]["id"]
    avail_res = await client.get(f"/api/v1/doctors/{doc_id}/timeslots")
    assert avail_res.status_code == 200
    assert len(avail_res.json()["data"]) == 2

    # 4. Doctor deletes one timeslot
    slot_to_delete = created_slots[0]["id"]
    del_res = await client.delete(f"/api/v1/doctors/me/timeslots/{slot_to_delete}", headers=headers)
    assert del_res.status_code == 200

    # 5. Public views remaining slots
    avail_res2 = await client.get(f"/api/v1/doctors/{doc_id}/timeslots")
    assert len(avail_res2.json()["data"]) == 1
