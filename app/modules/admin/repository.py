from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re
from app.common.enums import DoctorVerificationStatus

class AdminRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_all_doctors_admin(
        self,
        verification_status: Optional[DoctorVerificationStatus] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        include_deleted: bool = False,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if not include_deleted:
            query["is_deleted"] = {"$ne": True}

        if verification_status:
            query["verification_status"] = verification_status.value if hasattr(verification_status, "value") else verification_status
        if is_active is not None:
            query["is_active"] = is_active

        if search and search.strip():
            search_regex = {"$regex": re.escape(search.strip()), "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"bmdc_reg_number": search_regex},
                {"phone": search_regex},
                {"email": search_regex},
                {"specialties": search_regex},
                {"qualifications": search_regex}
            ]

        total = await self.db.doctors.count_documents(query)
        cursor = self.db.doctors.find(query).skip(skip).limit(limit).sort("created_at", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def update_doctor(self, doctor_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates["updated_at"] = datetime.now(timezone.utc)
        return await self.db.doctors.find_one_and_update(
            {"id": doctor_id},
            {"$set": updates},
            return_document=True
        )

    async def soft_delete_doctor(self, doctor_id: str) -> Optional[Dict[str, Any]]:
        existing = await self.db.doctors.find_one({"id": doctor_id})
        if not existing:
            return None
        now = datetime.now(timezone.utc)
        bmdc = existing.get("bmdc_reg_number", "")
        suffix = f"_deleted_{doctor_id}"
        new_bmdc = f"{bmdc}{suffix}" if not bmdc.endswith(suffix) else bmdc

        updated = await self.db.doctors.find_one_and_update(
            {"id": doctor_id},
            {
                "$set": {
                    "is_deleted": True,
                    "is_active": False,
                    "bmdc_reg_number": new_bmdc,
                    "original_bmdc": existing.get("original_bmdc") or bmdc,
                    "deleted_at": now,
                    "updated_at": now
                }
            },
            return_document=True
        )
        if updated:
            updated["bmdc_reg_number"] = existing.get("original_bmdc") or bmdc
        return updated

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

    # =========================================================================
    # User Management Repository Methods
    # =========================================================================
    async def get_all_users_admin(
        self,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        include_deleted: bool = False,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if not include_deleted:
            query["is_deleted"] = {"$ne": True}

        if role:
            query["role"] = role.value if hasattr(role, "value") else role
        if is_active is not None:
            query["is_active"] = is_active

        if search and search.strip():
            search_regex = {"$regex": re.escape(search.strip()), "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"phone": search_regex},
                {"email": search_regex},
                {"role": search_regex}
            ]

        total = await self.db.users.count_documents(query)
        cursor = self.db.users.find(query).skip(skip).limit(limit).sort("created_at", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.users.find_one({"id": user_id, "is_deleted": {"$ne": True}})

    async def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates["updated_at"] = datetime.now(timezone.utc)
        return await self.db.users.find_one_and_update(
            {"id": user_id},
            {"$set": updates},
            return_document=True
        )

    async def soft_delete_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        existing = await self.db.users.find_one({"id": user_id})
        if not existing:
            return None
        now = datetime.now(timezone.utc)
        phone = existing.get("phone", "")
        email = existing.get("email")
        suffix = f"_deleted_{user_id}"

        new_phone = f"{phone}{suffix}" if not phone.endswith(suffix) else phone
        new_email = f"{email}{suffix}" if email and not email.endswith(suffix) else email

        updated = await self.db.users.find_one_and_update(
            {"id": user_id},
            {
                "$set": {
                    "is_deleted": True,
                    "is_active": False,
                    "phone": new_phone,
                    "email": new_email,
                    "original_phone": existing.get("original_phone") or phone,
                    "original_email": existing.get("original_email") or email,
                    "deleted_at": now,
                    "updated_at": now
                }
            },
            return_document=True
        )
        if updated:
            updated["phone"] = existing.get("original_phone") or phone
            if email:
                updated["email"] = existing.get("original_email") or email
        return updated

    async def get_users_stats(self) -> Dict[str, Any]:
        filter_base = {"is_deleted": {"$ne": True}}
        total_users = await self.db.users.count_documents(filter_base)
        active_users = await self.db.users.count_documents({**filter_base, "is_active": True})
        total_regular_users = await self.db.users.count_documents({**filter_base, "role": {"$in": ["USER", "PATIENT"]}})
        total_doctors = await self.db.users.count_documents({**filter_base, "role": "DOCTOR"})
        total_nurses = await self.db.users.count_documents({**filter_base, "role": "NURSE"})
        total_admins = await self.db.users.count_documents({**filter_base, "role": "ADMIN"})
        total_developers = await self.db.users.count_documents({**filter_base, "role": "DEVELOPER"})

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_regular_users": total_regular_users,
            "total_doctors": total_doctors,
            "total_nurses": total_nurses,
            "total_admins": total_admins,
            "total_developers": total_developers
        }

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        total_users = await self.db.users.count_documents({"role": "USER", "is_active": True, "is_deleted": {"$ne": True}})
        doc_filter = {"is_deleted": {"$ne": True}}
        total_doctors = await self.db.doctors.count_documents(doc_filter)
        active_doctors = await self.db.doctors.count_documents({**doc_filter, "is_active": True, "is_verified": True})
        pending_verifications = await self.db.doctors.count_documents({**doc_filter, "verification_status": "PENDING"})
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

    async def get_audit_logs(
        self,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        user_id: Optional[str] = None,
        sort_by: str = "created_desc"
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if action and action != "ALL":
            query["action"] = action
        if target_type and target_type != "ALL":
            query["target_type"] = target_type
        if user_id and user_id.strip():
            query["user_id"] = user_id.strip()
        if search and search.strip():
            s = search.strip()
            query["$or"] = [
                {"action": {"$regex": s, "$options": "i"}},
                {"target_type": {"$regex": s, "$options": "i"}},
                {"target_id": {"$regex": s, "$options": "i"}},
                {"user_id": {"$regex": s, "$options": "i"}},
                {"ip_address": {"$regex": s, "$options": "i"}}
            ]

        sort_field = "created_at"
        sort_dir = -1
        if sort_by == "created_asc":
            sort_dir = 1
        elif sort_by == "action_asc":
            sort_field = "action"
            sort_dir = 1
        elif sort_by == "action_desc":
            sort_field = "action"
            sort_dir = -1

        total = await self.db.audit_logs.count_documents(query)
        cursor = self.db.audit_logs.find(query).sort(sort_field, sort_dir).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_audit_stats(self) -> Dict[str, Any]:
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_logs": {"$sum": 1},
                    "auth_events": {
                        "$sum": {
                            "$cond": [
                                {"$in": ["$action", ["USER_LOGIN", "USER_REGISTERED", "USER_CREATED", "PASSWORD_CHANGED", "PASSWORD_RESET"]]},
                                1,
                                0
                            ]
                        }
                    },
                    "pharmacy_events": {
                        "$sum": {
                            "$cond": [
                                {"$in": ["$action", ["MEDICINE_CREATED", "MEDICINE_UPDATED", "MEDICINE_DELETED", "MEDICINES_BULK_DELETED", "MEDEASY_INGESTION_TRIGGERED", "ORDER_PLACED", "ORDER_STATUS_CHANGED"]]},
                                1,
                                0
                            ]
                        }
                    },
                    "clinical_events": {
                        "$sum": {
                            "$cond": [
                                {"$in": ["$action", ["DOCTOR_VERIFIED", "DOCTOR_REJECTED", "DOCTOR_ACTIVATED", "DOCTOR_DEACTIVATED", "APPOINTMENT_BOOKED", "APPOINTMENT_CONFIRMED", "APPOINTMENT_CANCELLED", "CONSULTATION_COMPLETED", "DOCTOR_CREATED"]]},
                                1,
                                0
                            ]
                        }
                    },
                    "admin_events": {
                        "$sum": {
                            "$cond": [
                                {"$in": ["$action", ["SETTINGS_UPDATED", "PLATFORM_FEE_UPDATED", "USER_ACTIVATED", "USER_DEACTIVATED", "USER_DELETED", "USER_UPDATED"]]},
                                1,
                                0
                            ]
                        }
                    }
                }
            }
        ]
        results = await self.db.audit_logs.aggregate(pipeline).to_list(length=1)
        if results:
            r = results[0]
            return {
                "total_logs": r.get("total_logs", 0),
                "auth_events": r.get("auth_events", 0),
                "pharmacy_events": r.get("pharmacy_events", 0),
                "clinical_events": r.get("clinical_events", 0),
                "admin_events": r.get("admin_events", 0),
            }
        total = await self.db.audit_logs.count_documents({})
        return {
            "total_logs": total,
            "auth_events": 0,
            "pharmacy_events": 0,
            "clinical_events": 0,
            "admin_events": 0
        }
