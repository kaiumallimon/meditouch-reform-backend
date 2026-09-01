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
        return await self.db.doctors.find_one({"user_id": user_id, "is_deleted": {"$ne": True}})

    async def get_by_bmdc(self, bmdc_reg_number: str) -> Optional[Dict[str, Any]]:
        return await self.db.doctors.find_one({"bmdc_reg_number": bmdc_reg_number, "is_deleted": {"$ne": True}})

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
        min_experience: Optional[int] = None,
        min_rating: Optional[float] = None,
        sort_by: Optional[str] = "rating_desc",
        only_active_verified: bool = True,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if only_active_verified:
            query["is_verified"] = True
            query["is_active"] = True

        if specialty and specialty.strip() and specialty.upper() != "ALL":
            clean_spec = specialty.strip()
            query["specialties"] = {"$regex": re.escape(clean_spec), "$options": "i"}

        if min_fee is not None or max_fee is not None:
            fee_query = {}
            if min_fee is not None:
                fee_query["$gte"] = float(min_fee)
            if max_fee is not None:
                fee_query["$lte"] = float(max_fee)
            query["consultation_fee"] = fee_query

        if min_experience is not None:
            query["experience_years"] = {"$gte": int(min_experience)}

        if min_rating is not None:
            query["rating"] = {"$gte": float(min_rating)}

        if search and search.strip():
            search_regex = {"$regex": re.escape(search.strip()), "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"specialties": search_regex},
                {"qualifications": search_regex},
                {"bio": search_regex},
                {"hospital_affiliations": search_regex}
            ]

        # Sorting logic
        sort_criteria = [("rating", -1), ("total_reviews", -1)]
        if sort_by == "fee_asc":
            sort_criteria = [("consultation_fee", 1), ("rating", -1)]
        elif sort_by == "fee_desc":
            sort_criteria = [("consultation_fee", -1), ("rating", -1)]
        elif sort_by == "experience_desc":
            sort_criteria = [("experience_years", -1), ("rating", -1)]
        elif sort_by in ("consultations_desc", "popular"):
            sort_criteria = [("total_consultations", -1), ("rating", -1)]
        elif sort_by == "name_asc":
            sort_criteria = [("name", 1)]
        elif sort_by == "rating_desc":
            sort_criteria = [("rating", -1), ("total_reviews", -1)]

        total = await self.db.doctors.count_documents(query)
        cursor = self.db.doctors.find(query).skip(skip).limit(limit).sort(sort_criteria)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_specialties(self) -> List[Dict[str, Any]]:
        """Aggregate unique medical specialties with doctor counts."""
        pipeline = [
            {"$match": {"is_verified": True, "is_active": True}},
            {"$unwind": "$specialties"},
            {
                "$group": {
                    "_id": "$specialties",
                    "doctor_count": {"$sum": 1}
                }
            },
            {"$sort": {"doctor_count": -1, "_id": 1}}
        ]
        results = await self.db.doctors.aggregate(pipeline).to_list(length=100)
        return [{"specialty": doc["_id"], "doctor_count": doc["doctor_count"]} for doc in results]

    async def get_featured_doctors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top-rated active verified doctors for mobile showcase."""
        cursor = self.db.doctors.find(
            {"is_verified": True, "is_active": True}
        ).sort([("rating", -1), ("total_reviews", -1)]).limit(limit)
        return await cursor.to_list(length=limit)

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

