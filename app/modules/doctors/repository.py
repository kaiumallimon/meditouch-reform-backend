from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re
from app.common.enums import TimeslotStatus, DoctorVerificationStatus

class DoctorRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, doctor_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.doctors.find_one({"id": doctor_id})

    async def get_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.doctors.find_one({"user_id": user_id})

    async def get_by_bmdc(self, bmdc_reg_number: str) -> Optional[Dict[str, Any]]:
        return await self.db.doctors.find_one({"bmdc_reg_number": bmdc_reg_number})

    async def create_doctor_profile(self, doctor_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in doctor_doc:
            doctor_doc["id"] = str(uuid.uuid4())
        if "created_at" not in doctor_doc:
            doctor_doc["created_at"] = datetime.now(timezone.utc)
        doctor_doc["updated_at"] = datetime.now(timezone.utc)
        await self.db.doctors.insert_one(doctor_doc)
        return doctor_doc

    create = create_doctor_profile

    async def update_doctor_profile(self, doctor_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates["updated_at"] = datetime.now(timezone.utc)
        await self.db.doctors.update_one({"id": doctor_id}, {"$set": updates})
        return await self.get_by_id(doctor_id)

    async def search_doctors(
        self,
        specialty: Optional[str] = None,
        search: Optional[str] = None,
        min_fee: Optional[float] = None,
        max_fee: Optional[float] = None,
        only_active_verified: bool = True,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if only_active_verified:
            query["is_verified"] = True
            query["is_active"] = True

        if specialty:
            query["specialties"] = {"$regex": f"^{re.escape(specialty)}$", "$options": "i"}

        if min_fee is not None or max_fee is not None:
            fee_query = {}
            if min_fee is not None:
                fee_query["$gte"] = min_fee
            if max_fee is not None:
                fee_query["$lte"] = max_fee
            query["consultation_fee"] = fee_query

        if search:
            search_regex = {"$regex": re.escape(search), "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"specialties": search_regex},
                {"qualifications": search_regex}
            ]

        total = await self.db.doctors.count_documents(query)
        cursor = self.db.doctors.find(query).skip(skip).limit(limit).sort("rating", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def create_timeslot(self, slot_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in slot_doc:
            slot_doc["id"] = str(uuid.uuid4())
        if "created_at" not in slot_doc:
            slot_doc["created_at"] = datetime.now(timezone.utc)
        slot_doc["status"] = TimeslotStatus.AVAILABLE.value
        await self.db.timeslots.insert_one(slot_doc)
        return slot_doc

    async def get_doctor_timeslots(
        self,
        doctor_id: str,
        status: Optional[TimeslotStatus] = None,
        start_time_gte: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"doctor_id": doctor_id}
        if status:
            query["status"] = status.value if isinstance(status, TimeslotStatus) else status
        if start_time_gte:
            query["start_time"] = {"$gte": start_time_gte}

        cursor = self.db.timeslots.find(query).sort("start_time", 1)
        return await cursor.to_list(length=200)

    async def get_timeslot_by_id(self, timeslot_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.timeslots.find_one({"id": timeslot_id})

    async def reserve_timeslot_atomic(self, timeslot_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically reserve an available timeslot. If already reserved or booked, returns None.
        Prevents race condition and double-booking.
        """
        return await self.db.timeslots.find_one_and_update(
            {"id": timeslot_id, "status": TimeslotStatus.AVAILABLE.value},
            {"$set": {"status": TimeslotStatus.RESERVED.value, "updated_at": datetime.now(timezone.utc)}},
            return_document=True
        )

    async def confirm_timeslot_atomic(self, timeslot_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.timeslots.find_one_and_update(
            {"id": timeslot_id},
            {"$set": {"status": TimeslotStatus.BOOKED.value, "updated_at": datetime.now(timezone.utc)}},
            return_document=True
        )

    async def release_timeslot_atomic(self, timeslot_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.timeslots.find_one_and_update(
            {"id": timeslot_id},
            {"$set": {"status": TimeslotStatus.AVAILABLE.value, "updated_at": datetime.now(timezone.utc)}},
            return_document=True
        )

    async def delete_timeslot(self, timeslot_id: str, doctor_id: str) -> bool:
        res = await self.db.timeslots.delete_one({
            "id": timeslot_id,
            "doctor_id": doctor_id,
            "status": TimeslotStatus.AVAILABLE.value
        })
        return res.deleted_count > 0

