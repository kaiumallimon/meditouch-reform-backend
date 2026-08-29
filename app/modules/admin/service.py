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
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    AdminUserResponse,
    AdminUsersStats,
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

        user_doc = {
            "id": user_id,
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": str(req.email).strip().lower() if req.email else None,
            "password_hash": hashed_pwd,
            "role": UserRole.DOCTOR.value,
            "is_active": True,
            "is_verified": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "avatar_url": req.avatar_url,
            "is_deleted": False
        }
        await self.auth_repo.create_user(user_doc)

        doctor_id = str(uuid.uuid4())
        doctor_doc = {
            "id": doctor_id,
            "user_id": user_id,
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": str(req.email).strip().lower() if req.email else None,
            "bmdc_reg_number": req.bmdc_reg_number.strip().upper(),
            "specialties": req.specialties or [],
            "qualifications": req.qualifications or [],
            "experience_years": req.experience_years or 0,
            "consultation_fee": req.consultation_fee or 0.0,
            "bio": req.bio or "",
            "verification_status": DoctorVerificationStatus.PENDING.value,
            "is_verified": False,
            "is_active": False,
            "avatar_url": req.avatar_url,
            "rating": 5.0,
            "total_reviews": 0,
            "total_consultations": 0,
            "verification_documents": [d.model_dump() for d in (req.verification_documents or [])],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "is_deleted": False
        }
        created_doctor = await self.doctor_repo.create(doctor_doc)

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_CREATED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"name": req.name, "phone": clean_phone, "email": req.email, "bmdc": req.bmdc_reg_number}
        )

        if req.email:
            asyncio.create_task(
                EmailService.send_doctor_welcome_email(
                    name=req.name.strip(),
                    phone=clean_phone,
                    email=str(req.email).strip().lower(),
                    passphrase=raw_password
                )
            )

        return DoctorProfileResponse(**created_doctor)

    async def update_doctor(
        self,
        doctor_id: str,
        req: AdminUpdateDoctorRequest,
        admin_id: str
    ) -> DoctorProfileResponse:
        existing = await self.doctor_repo.get_by_id(doctor_id)
        if not existing or existing.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        updates: Dict[str, Any] = {}
        user_updates: Dict[str, Any] = {}

        if req.name is not None:
            updates["name"] = req.name.strip()
            user_updates["name"] = req.name.strip()

        if req.phone is not None:
            clean_phone = sanitize_phone_number(req.phone)
            other_user = await self.auth_repo.get_by_phone(clean_phone)
            if other_user and other_user.get("id") != existing.get("user_id"):
                raise ConflictException("Another user already exists with this phone number")
            updates["phone"] = clean_phone
            user_updates["phone"] = clean_phone

        if req.email is not None:
            clean_email = str(req.email).strip().lower()
            other_email = await self.auth_repo.get_by_email(clean_email)
            if other_email and other_email.get("id") != existing.get("user_id"):
                raise ConflictException("Another user already exists with this email")
            updates["email"] = clean_email
            user_updates["email"] = clean_email

        if req.bmdc_reg_number is not None:
            clean_bmdc = req.bmdc_reg_number.strip().upper()
            other_bmdc = await self.doctor_repo.get_by_bmdc(clean_bmdc)
            if other_bmdc and other_bmdc.get("id") != doctor_id:
                raise ConflictException("Another doctor already exists with this BMDC number")
            updates["bmdc_reg_number"] = clean_bmdc

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
            updates["verification_documents"] = [d.model_dump() for d in req.verification_documents]
        if req.is_active is not None:
            updates["is_active"] = req.is_active
            user_updates["is_active"] = req.is_active
        if req.verification_status is not None:
            updates["verification_status"] = req.verification_status.value
            updates["is_verified"] = req.verification_status == DoctorVerificationStatus.VERIFIED

        if not updates and not user_updates:
            return DoctorProfileResponse(**existing)

        updated_doctor = await self.repo.update_doctor(doctor_id, updates)

        if user_updates and existing.get("user_id"):
            user_updates["updated_at"] = datetime.now(timezone.utc)
            await self.db.users.update_one(
                {"id": existing["user_id"]},
                {"$set": user_updates}
            )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_UPDATED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"updated_fields": list(updates.keys())}
        )

        return DoctorProfileResponse(**updated_doctor)

    async def soft_delete_doctor(self, doctor_id: str, admin_id: str) -> DoctorProfileResponse:
        existing = await self.doctor_repo.get_by_id(doctor_id)
        if not existing or existing.get("is_deleted"):
            raise NotFoundException("Doctor not found")

        updated_doctor = await self.repo.soft_delete_doctor(doctor_id)

        if existing.get("user_id"):
            now = datetime.now(timezone.utc)
            await self.db.users.update_one(
                {"id": existing["user_id"]},
                {"$set": {"is_deleted": True, "is_active": False, "deleted_at": now, "updated_at": now}}
            )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.DOCTOR_DELETED,
            target_type="DOCTOR",
            target_id=doctor_id,
            details={"name": existing.get("name"), "bmdc": existing.get("bmdc_reg_number")}
        )

        return DoctorProfileResponse(**updated_doctor)

    async def verify_doctor(
        self,
        doctor_id: str,
        req: VerifyDoctorRequest,
        admin_id: str
    ) -> DoctorProfileResponse:
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

    # =========================================================================
    # User Management Service Methods
    # =========================================================================
    async def create_user_account(self, req: AdminCreateUserRequest, admin_id: str) -> AdminUserResponse:
        clean_phone = sanitize_phone_number(req.phone)

        existing_phone = await self.auth_repo.get_by_phone(clean_phone)
        if existing_phone:
            raise ConflictException("A user with this phone number already exists")

        if req.email:
            existing_email = await self.auth_repo.get_by_email(str(req.email).strip().lower())
            if existing_email:
                raise ConflictException("A user with this email already exists")

        raw_password = req.password.strip() if req.password and req.password.strip() else generate_readable_passphrase()
        hashed_pwd = hash_password(raw_password)
        user_id = str(uuid.uuid4())
        role_value = req.role.value if hasattr(req.role, "value") else str(req.role)

        user_doc = {
            "id": user_id,
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": str(req.email).strip().lower() if req.email else None,
            "password_hash": hashed_pwd,
            "role": role_value,
            "avatar_url": req.avatar_url,
            "is_active": req.is_active,
            "is_verified": True,
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        await self.auth_repo.create_user(user_doc)

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.USER_CREATED,
            target_type="USER",
            target_id=user_id,
            details={"name": req.name, "phone": clean_phone, "email": req.email, "role": role_value}
        )

        if req.email:
            asyncio.create_task(
                EmailService.send_user_welcome_email(
                    name=req.name.strip(),
                    phone=clean_phone,
                    email=str(req.email).strip().lower(),
                    passphrase=raw_password,
                    role=role_value
                )
            )

        return AdminUserResponse(**user_doc)

    async def list_all_users_admin(
        self,
        role: Optional[str],
        is_active: Optional[bool],
        search: Optional[str],
        pagination: PaginationParams
    ) -> PaginatedResponse[AdminUserResponse]:
        users, total = await self.repo.get_all_users_admin(
            role=role,
            is_active=is_active,
            search=search,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [AdminUserResponse(**u) for u in users]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_user_by_id(self, user_id: str) -> AdminUserResponse:
        user = await self.repo.get_user_by_id(user_id)
        if not user:
            raise NotFoundException("User not found")
        return AdminUserResponse(**user)

    async def update_user_account(
        self,
        user_id: str,
        req: AdminUpdateUserRequest,
        admin_id: str
    ) -> AdminUserResponse:
        existing = await self.repo.get_user_by_id(user_id)
        if not existing:
            raise NotFoundException("User not found")

        updates: Dict[str, Any] = {}

        if req.name is not None:
            updates["name"] = req.name.strip()
        if req.phone is not None:
            clean_phone = sanitize_phone_number(req.phone)
            other_user = await self.auth_repo.get_by_phone(clean_phone)
            if other_user and other_user.get("id") != user_id:
                raise ConflictException("Another user already exists with this phone number")
            updates["phone"] = clean_phone
        if req.email is not None:
            clean_email = str(req.email).strip().lower()
            other_email = await self.auth_repo.get_by_email(clean_email)
            if other_email and other_email.get("id") != user_id:
                raise ConflictException("Another user already exists with this email")
            updates["email"] = clean_email
        if req.role is not None:
            updates["role"] = req.role.value if hasattr(req.role, "value") else str(req.role)
        if req.avatar_url is not None:
            updates["avatar_url"] = req.avatar_url
        if req.is_active is not None:
            if user_id == admin_id and req.is_active is False:
                raise BadRequestException("You cannot deactivate your own active administrator account.")
            updates["is_active"] = req.is_active

        if not updates:
            return AdminUserResponse(**existing)

        updated_user = await self.repo.update_user(user_id, updates)

        # Sync to doctor collection if applicable
        if existing.get("role") == "DOCTOR":
            doc_updates = {k: v for k, v in updates.items() if k in ["name", "phone", "email", "avatar_url", "is_active"]}
            if doc_updates:
                doc_updates["updated_at"] = datetime.now(timezone.utc)
                await self.db.doctors.update_one({"user_id": user_id}, {"$set": doc_updates})

        action = AuditAction.USER_ACTIVATED if (req.is_active is True and not existing.get("is_active")) else \
                 AuditAction.USER_DEACTIVATED if (req.is_active is False and existing.get("is_active")) else \
                 AuditAction.USER_UPDATED

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=action,
            target_type="USER",
            target_id=user_id,
            details={"updated_fields": list(updates.keys())}
        )

        return AdminUserResponse(**updated_user)

    async def soft_delete_user_account(self, user_id: str, admin_id: str) -> AdminUserResponse:
        if user_id == admin_id:
            raise BadRequestException("You cannot delete your own logged-in administrator account.")

        existing = await self.repo.get_user_by_id(user_id)
        if not existing:
            raise NotFoundException("User not found")

        # Soft delete user
        deleted_user = await self.repo.soft_delete_user(user_id)

        # Also soft delete doctor record if doctor
        if existing.get("role") == "DOCTOR":
            now = datetime.now(timezone.utc)
            await self.db.doctors.update_one(
                {"user_id": user_id},
                {"$set": {"is_deleted": True, "is_active": False, "deleted_at": now, "updated_at": now}}
            )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.USER_DELETED,
            target_type="USER",
            target_id=user_id,
            details={"name": existing.get("name"), "phone": existing.get("phone"), "role": existing.get("role")}
        )

        return AdminUserResponse(**deleted_user)

    async def send_password_recovery(self, user_id: str, admin_id: str) -> Dict[str, Any]:
        user = await self.repo.get_user_by_id(user_id)
        if not user:
            raise NotFoundException("User not found")

        if not user.get("email"):
            raise BadRequestException("User does not have an email address associated with their account")

        new_passphrase = generate_readable_passphrase()
        new_hashed = hash_password(new_passphrase)

        await self.db.users.update_one(
            {"id": user_id},
            {"$set": {"password_hash": new_hashed, "updated_at": datetime.now(timezone.utc)}}
        )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.PASSWORD_RESET,
            target_type="USER",
            target_id=user_id,
            details={"name": user.get("name"), "email": user.get("email"), "role": user.get("role")}
        )

        # Dispatch recovery email via SMTP
        asyncio.create_task(
            EmailService.send_password_recovery_email(
                name=user.get("name", "User"),
                phone=user.get("phone", ""),
                email=user.get("email"),
                passphrase=new_passphrase,
                role=user.get("role", "USER")
            )
        )

        return {
            "message": f"Password recovery passphrase generated and dispatched via email to {user.get('email')}",
            "email": user.get("email")
        }

    async def get_users_stats(self) -> AdminUsersStats:
        stats = await self.repo.get_users_stats()
        return AdminUsersStats(**stats)

    async def get_dashboard_stats(self) -> AdminDashboardStats:
        stats = await self.repo.get_dashboard_stats()
        return AdminDashboardStats(**stats)

    async def get_audit_logs(self, pagination: PaginationParams) -> PaginatedResponse[AuditLogEntry]:
        docs, total = await self.repo.get_audit_logs(skip=pagination.skip, limit=pagination.limit)
        items = [AuditLogEntry(**d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)
