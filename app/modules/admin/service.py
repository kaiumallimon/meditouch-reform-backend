from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

from app.modules.admin.repository import AdminRepository
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.admin.schemas import (
    CreateDoctorAccountRequest,
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

        hashed_pwd = hash_password(req.password)
        user_id = str(uuid.uuid4())
        doctor_id = str(uuid.uuid4())

        user_doc = {
            "id": user_id,
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": req.email.lower() if req.email else None,
            "hashed_password": hashed_pwd,
            "role": UserRole.DOCTOR.value,
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

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_CREATED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"bmdc": req.bmdc_reg_number, "phone": clean_phone}
        )

        return DoctorProfileResponse(**created)

    async def add_verification_document(
        self,
        doctor_id: str,
        doc_req: DoctorVerificationDocSchema,
        admin_id: str
    ) -> DoctorProfileResponse:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc:
            raise NotFoundException("Doctor not found")

        updated = await self.repo.add_verification_document(doctor_id, doc_req.model_dump())
        return DoctorProfileResponse(**updated)

    async def verify_doctor(self, doctor_id: str, req: VerifyDoctorRequest, admin_id: str) -> DoctorProfileResponse:
        doc = await self.doctor_repo.get_by_id(doctor_id)
        if not doc:
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
        if not doc:
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
        pagination: PaginationParams
    ) -> PaginatedResponse[DoctorProfileResponse]:
        docs, total = await self.repo.get_all_doctors_admin(
            verification_status=verification_status,
            is_active=is_active,
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

