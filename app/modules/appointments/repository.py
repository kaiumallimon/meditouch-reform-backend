from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
from app.common.enums import AppointmentStatus

class AppointmentRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, appointment_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.appointments.find_one({"id": appointment_id})

    async def get_by_invoice(self, merchant_invoice_number: str) -> Optional[Dict[str, Any]]:
        return await self.db.appointments.find_one({"merchant_invoice_number": merchant_invoice_number})

    async def get_by_payment_id(self, payment_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.appointments.find_one({"payment_id": payment_id})

    async def create(self, appointment_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in appointment_doc:
            appointment_doc["id"] = str(uuid.uuid4())
        if "created_at" not in appointment_doc:
            appointment_doc["created_at"] = datetime.now(timezone.utc)
        appointment_doc["updated_at"] = datetime.now(timezone.utc)
        await self.db.appointments.insert_one(appointment_doc)
        return appointment_doc

    async def update_status(
        self,
        appointment_id: str,
        status: AppointmentStatus,
        payment_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        updates: Dict[str, Any] = {
            "status": status.value if isinstance(status, AppointmentStatus) else status,
            "updated_at": datetime.now(timezone.utc)
        }
        if payment_id:
            updates["payment_id"] = payment_id

        return await self.db.appointments.find_one_and_update(
            {"id": appointment_id},
            {"$set": updates},
            return_document=True
        )

    async def get_patient_appointments(
        self,
        patient_id: str,
        status: Optional[AppointmentStatus] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {"patient_id": patient_id}
        if status:
            query["status"] = status.value if isinstance(status, AppointmentStatus) else status

        total = await self.db.appointments.count_documents(query)
        cursor = self.db.appointments.find(query).skip(skip).limit(limit).sort("start_time", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_doctor_appointments(
        self,
        doctor_id: str,
        status: Optional[AppointmentStatus] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {"doctor_id": doctor_id}
        if status:
            query["status"] = status.value if isinstance(status, AppointmentStatus) else status

        total = await self.db.appointments.count_documents(query)
        cursor = self.db.appointments.find(query).skip(skip).limit(limit).sort("start_time", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_upcoming_confirmed_appointments_in_window(
        self,
        start_time_from: datetime,
        start_time_to: datetime
    ) -> List[Dict[str, Any]]:
        query = {
            "status": AppointmentStatus.CONFIRMED.value,
            "start_time": {"$gte": start_time_from, "$lte": start_time_to}
        }
        cursor = self.db.appointments.find(query)
        return await cursor.to_list(length=500)

