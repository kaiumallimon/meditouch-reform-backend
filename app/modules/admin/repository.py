from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
from app.common.enums import DoctorVerificationStatus

class AdminRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_all_doctors_admin(
        self,
        verification_status: Optional[DoctorVerificationStatus] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if verification_status:
            query["verification_status"] = verification_status.value if hasattr(verification_status, "value") else verification_status
        if is_active is not None:
            query["is_active"] = is_active

        total = await self.db.doctors.count_documents(query)
        cursor = self.db.doctors.find(query).skip(skip).limit(limit).sort("created_at", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def add_verification_document(self, doctor_id: str, doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        doc["uploaded_at"] = datetime.now(timezone.utc)
        return await self.db.doctors.find_one_and_update(
            {"id": doctor_id},
            {
                "$push": {"verification_documents": doc},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            },
            return_document=True
        )

    async def update_verification_status(
        self,
        doctor_id: str,
        status: DoctorVerificationStatus,
        rejection_reason: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        updates = {
            "verification_status": status.value if hasattr(status, "value") else status,
            "is_verified": status == DoctorVerificationStatus.VERIFIED,
            "is_active": status == DoctorVerificationStatus.VERIFIED,
            "rejection_reason": rejection_reason,
            "verified_at": datetime.now(timezone.utc) if status == DoctorVerificationStatus.VERIFIED else None,
            "updated_at": datetime.now(timezone.utc)
        }
        return await self.db.doctors.find_one_and_update(
            {"id": doctor_id},
            {"$set": updates},
            return_document=True
        )

    async def update_doctor_active_status(self, doctor_id: str, is_active: bool) -> Optional[Dict[str, Any]]:
        return await self.db.doctors.find_one_and_update(
            {"id": doctor_id},
            {"$set": {"is_active": is_active, "updated_at": datetime.now(timezone.utc)}},
            return_document=True
        )

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        total_users = await self.db.users.count_documents({"role": "USER"})
        total_doctors = await self.db.doctors.count_documents({})
        active_doctors = await self.db.doctors.count_documents({"is_active": True, "is_verified": True})
        pending_verifications = await self.db.doctors.count_documents({"verification_status": "PENDING"})
        total_appointments = await self.db.appointments.count_documents({})
        completed_consultations = await self.db.appointments.count_documents({"status": "COMPLETED"})
        total_orders = await self.db.orders.count_documents({})

        pipeline = [
            {"$match": {"status": "COMPLETED"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]
        rev_res = await self.db.payments.aggregate(pipeline).to_list(1)
        total_rev = rev_res[0]["total"] if rev_res else 0.0

        return {
            "total_users": total_users,
            "total_doctors": total_doctors,
            "active_doctors": active_doctors,
            "pending_doctor_verifications": pending_verifications,
            "total_appointments": total_appointments,
            "completed_consultations": completed_consultations,
            "total_orders": total_orders,
            "total_revenue_bdt": round(total_rev, 2)
        }

    async def get_audit_logs(self, skip: int = 0, limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        total = await self.db.audit_logs.count_documents({})
        cursor = self.db.audit_logs.find({}).skip(skip).limit(limit).sort("created_at", -1)
        items = await cursor.to_list(length=limit)
        return items, total

