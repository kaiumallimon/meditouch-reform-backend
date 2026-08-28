from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re

from app.modules.admin.repository import AdminRepository
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.admin.schemas import (
    CreateDoctorAccountRequest,
    AdminUpdateDoctorRequest,
    VerifyDoctorRequest,
    UpdateDoctorStatusRequest,
    AdminDashboardStats,
    AuditLogEntry
)
from app.modules.doctors.schemas import DoctorProfileResponse, DoctorVerificationDocSchema
from app.common.enums import UserRole, DoctorVerificationStatus, AuditAction, NotificationType
from app.common.utils import sanitize_phone_number
from app.common.pagination import PaginationParams, PaginatedResponse
from app.core.security import hash_password
from app.core.exceptions import ConflictException, NotFoundException, BadRequestException
from app.core.logging import log_audit_event
from app.common.passphrase import generate_readable_passphrase
from app.integrations.smtp import EmailService
import asyncio

class AdminService:
    def __init__(
        self,
        repo: AdminRepository,
        auth_repo: AuthRepository,
        doctor_repo: DoctorRepository,
        db: AsyncIOMotorDatabase
    ):
        self.repo = repo
        self.auth_repo = auth_repo
        self.doctor_repo = doctor_repo
        self.db = db

    async def create_doctor_account(self, req: CreateDoctorAccountRequest, admin_id: str) -> DoctorProfileResponse:
        clean_phone = sanitize_phone_number(req.phone)

        existing_phone = await self.auth_repo.get_by_phone(clean_phone)
        if existing_phone:
            raise ConflictException("A user with this phone number already exists")

        if req.email:
            existing_email = await self.auth_repo.get_by_email(req.email)
            if existing_email:
                raise ConflictException("A user with this email already exists")

        existing_bmdc = await self.doctor_repo.get_by_bmdc(req.bmdc_reg_number)
        if existing_bmdc:
            raise ConflictException("A doctor with this BMDC registration number already exists")

        raw_password = req.password.strip() if req.password and req.password.strip() else generate_readable_passphrase()
        hashed_pwd = hash_password(raw_password)
        user_id = str(uuid.uuid4())
        doctor_id = str(uuid.uuid4())

        user_doc = {
            "id": user_id,
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": req.email.lower() if req.email else None,
            "hashed_password": hashed_pwd,
            "role": UserRole.DOCTOR.value,
            "avatar_url": req.avatar_url,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        await self.auth_repo.create_user(user_doc)

        docs = [d.model_dump() for d in req.verification_documents] if req.verification_documents else []
        for d in docs:
            d["uploaded_at"] = datetime.now(timezone.utc)

        doctor_doc = {
            "id": doctor_id,
            "user_id": user_id,
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": req.email.lower() if req.email else None,
            "avatar_url": req.avatar_url,
            "bmdc_reg_number": req.bmdc_reg_number.strip(),
            "specialties": req.specialties or [],
            "qualifications": req.qualifications or [],
            "experience_years": req.experience_years,
            "consultation_fee": req.consultation_fee,
            "bio": req.bio,
            "is_verified": False,
            "verification_status": DoctorVerificationStatus.PENDING.value,
            "is_active": False,
            "rating": 5.0,
            "total_reviews": 0,
            "total_consultations": 0,
            "verification_documents": docs,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        created = await self.doctor_repo.create_doctor_profile(doctor_doc)

        # Asynchronously dispatch welcome email with credentials
        if req.email:
            asyncio.create_task(
                EmailService.send_doctor_welcome_email(
                    name=req.name.strip(),
                    phone=clean_phone,
                    email=req.email.lower(),
                    passphrase=raw_password
                )
            )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_CREATED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"bmdc": req.bmdc_reg_number, "phone": clean_phone, "email": req.email}
        )

        return DoctorProfileResponse(**created)

    async def update_doctor(self, doctor_id: str, req: AdminUpdateDoctorRequest, admin_id: str) -> DoctorProfileResponse:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        updates: Dict[str, Any] = {}
        user_updates: Dict[str, Any] = {}

        if req.name is not None:
            updates["name"] = req.name.strip()
            user_updates["name"] = req.name.strip()

        if req.phone is not None:
            clean_phone = sanitize_phone_number(req.phone)
            existing_phone = await self.auth_repo.get_by_phone(clean_phone)
            if existing_phone and existing_phone.get("id") != doc["user_id"]:
                raise ConflictException("A user with this phone number already exists")
            updates["phone"] = clean_phone
            user_updates["phone"] = clean_phone

        if req.email is not None:
            existing_email = await self.auth_repo.get_by_email(req.email)
            if existing_email and existing_email.get("id") != doc["user_id"]:
                raise ConflictException("A user with this email already exists")
            updates["email"] = req.email.lower()
            user_updates["email"] = req.email.lower()

        if req.bmdc_reg_number is not None:
            existing_bmdc = await self.doctor_repo.get_by_bmdc(req.bmdc_reg_number)
            if existing_bmdc and existing_bmdc.get("id") != doctor_id:
                raise ConflictException("A doctor with this BMDC registration number already exists")
            updates["bmdc_reg_number"] = req.bmdc_reg_number.strip()

        if req.specialties is not None:
            updates["specialties"] = req.specialties
        if req.qualifications is not None:
            updates["qualifications"] = req.qualifications
        if req.experience_years is not None:
            updates["experience_years"] = req.experience_years
        if req.consultation_fee is not None:
            updates["consultation_fee"] = req.consultation_fee
        if req.bio is not None:
            updates["bio"] = req.bio
        if req.avatar_url is not None:
            updates["avatar_url"] = req.avatar_url
            user_updates["avatar_url"] = req.avatar_url

        if req.verification_documents is not None:
            docs = [d.model_dump() for d in req.verification_documents]
            for d in docs:
                if not d.get("uploaded_at"):
                    d["uploaded_at"] = datetime.now(timezone.utc)
            updates["verification_documents"] = docs

        if req.is_active is not None:
            updates["is_active"] = req.is_active
            user_updates["is_active"] = req.is_active

        if req.verification_status is not None:
            updates["verification_status"] = req.verification_status.value
            updates["is_verified"] = req.verification_status == DoctorVerificationStatus.VERIFIED

        if user_updates:
            await self.db.users.update_one({"id": doc["user_id"]}, {"$set": {**user_updates, "updated_at": datetime.now(timezone.utc)}})

        updated = await self.repo.update_doctor(doctor_id, updates)

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_UPDATED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"updated_fields": list(updates.keys())}
        )

        return DoctorProfileResponse(**updated)

    async def soft_delete_doctor(self, doctor_id: str, admin_id: str) -> bool:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        # Soft delete doctor profile and deactivate user account
        await self.repo.soft_delete_doctor(doctor_id)
        await self.db.users.update_one(
            {"id": doc["user_id"]},
            {"$set": {"is_active": False, "is_deleted": True, "updated_at": datetime.now(timezone.utc)}}
        )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_DELETED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"doctor_name": doc.get("name"), "bmdc": doc.get("bmdc_reg_number")}
        )

        return True

    async def add_verification_document(
        self,
        doctor_id: str,
        doc_req: DoctorVerificationDocSchema,
        admin_id: str
    ) -> DoctorProfileResponse:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        updated = await self.repo.add_verification_document(doctor_id, doc_req.model_dump())
        return DoctorProfileResponse(**updated)

    async def verify_doctor(self, doctor_id: str, req: VerifyDoctorRequest, admin_id: str) -> DoctorProfileResponse:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        updated = await self.repo.update_verification_status(
            doctor_id=doctor_id,
            status=req.status,
            rejection_reason=req.rejection_reason
        )

        action = AuditAction.DOCTOR_VERIFIED if req.status == DoctorVerificationStatus.VERIFIED else AuditAction.DOCTOR_REJECTED
        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=action,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"status": req.status.value, "reason": req.rejection_reason}
        )

        await self.db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": doc["user_id"],
            "type": NotificationType.SYSTEM.value,
            "title": f"Doctor Profile {req.status.value}",
            "message": f"Your doctor verification status is now {req.status.value}. {req.rejection_reason or ''}",
            "payload": {"doctor_id": doctor_id, "status": req.status.value},
            "is_read": False,
            "created_at": datetime.now(timezone.utc)
        })

        return DoctorProfileResponse(**updated)

    async def update_doctor_active_status(
        self,
        doctor_id: str,
        req: UpdateDoctorStatusRequest,
        admin_id: str
    ) -> DoctorProfileResponse:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        if req.is_active and not doc.get("is_verified", False):
            raise BadRequestException("Cannot activate an unverified doctor")

        updated = await self.repo.update_doctor_active_status(doctor_id, req.is_active)

        action = AuditAction.DOCTOR_ACTIVATED if req.is_active else AuditAction.DOCTOR_DEACTIVATED
        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=action,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"is_active": req.is_active}
        )

        return DoctorProfileResponse(**updated)

    async def list_all_doctors_admin(
        self,
        verification_status: Optional[DoctorVerificationStatus],
        is_active: Optional[bool],
        search: Optional[str],
        pagination: PaginationParams
    ) -> PaginatedResponse[DoctorProfileResponse]:
        docs, total = await self.repo.get_all_doctors_admin(
            verification_status=verification_status,
            is_active=is_active,
            search=search,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [DoctorProfileResponse(**d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_dashboard_stats(self) -> AdminDashboardStats:
        stats = await self.repo.get_dashboard_stats()
        return AdminDashboardStats(**stats)

    async def get_audit_logs(self, pagination: PaginationParams) -> PaginatedResponse[AuditLogEntry]:
        docs, total = await self.repo.get_audit_logs(skip=pagination.skip, limit=pagination.limit)
        items = [AuditLogEntry(**d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)
