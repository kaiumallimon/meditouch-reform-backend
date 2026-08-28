from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

class ConsultationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_appointment_id(self, appointment_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.consultation_records.find_one({"appointment_id": appointment_id})

    async def create_or_update_record(self, record_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in record_doc:
            record_doc["id"] = str(uuid.uuid4())
        record_doc["updated_at"] = datetime.now(timezone.utc)
        if "completed_at" not in record_doc:
            record_doc["completed_at"] = datetime.now(timezone.utc)

        await self.db.consultation_records.update_one(
            {"appointment_id": record_doc["appointment_id"]},
            {"$set": record_doc},
            upsert=True
        )
        return record_doc

    async def get_patient_history(self, patient_id: str) -> List[Dict[str, Any]]:
        cursor = self.db.consultation_records.find({"patient_id": patient_id}).sort("completed_at", -1)
        return await cursor.to_list(length=100)

