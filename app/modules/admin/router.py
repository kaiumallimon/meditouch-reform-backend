from fastapi import APIRouter, Depends, Query, status
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.admin.repository import AdminRepository
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.admin.service import AdminService
from app.modules.admin.schemas import (
    CreateDoctorAccountRequest,
    AdminUpdateDoctorRequest,
    VerifyDoctorRequest,
    UpdateDoctorStatusRequest,
    AdminDashboardStats,
    AuditLogEntry
)
from app.modules.doctors.schemas import DoctorProfileResponse, DoctorVerificationDocSchema
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.responses import APIResponse
from app.common.enums import DoctorVerificationStatus, UserRole
from app.core.security import get_current_user_payload
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/admin", tags=["Admin Web Dashboard"])

def get_admin_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> AdminService:
    admin_repo = AdminRepository(db)
    auth_repo = AuthRepository(db)
    doc_repo = DoctorRepository(db)
    return AdminService(admin_repo, auth_repo, doc_repo, db)

def require_admin_role(payload: dict = Depends(get_current_user_payload)) -> dict:
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Access restricted to platform administrators only")
    return payload

@router.post("/doctors", response_model=APIResponse[DoctorProfileResponse], status_code=status.HTTP_201_CREATED)
async def create_doctor(
    req: CreateDoctorAccountRequest,
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    doc = await service.create_doctor_account(req, payload["sub"])
    return APIResponse(success=True, message="Doctor account and profile created", data=doc)

@router.get("/doctors", response_model=APIResponse[PaginatedResponse[DoctorProfileResponse]])
async def list_doctors(
    verification_status: Optional[DoctorVerificationStatus] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    pagination = PaginationParams(page=page, limit=limit)
    res = await service.list_all_doctors_admin(verification_status, is_active, search, pagination)
    return APIResponse(success=True, message="Doctors list retrieved", data=res)

@router.patch("/doctors/{doctor_id}", response_model=APIResponse[DoctorProfileResponse])
async def update_doctor(
    doctor_id: str,
    req: AdminUpdateDoctorRequest,
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    doc = await service.update_doctor(doctor_id, req, payload["sub"])
    return APIResponse(success=True, message="Doctor profile updated successfully", data=doc)

@router.delete("/doctors/{doctor_id}", response_model=APIResponse[dict])
async def delete_doctor(
    doctor_id: str,
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    await service.soft_delete_doctor(doctor_id, payload["sub"])
    return APIResponse(success=True, message="Doctor profile removed successfully", data={"id": doctor_id, "deleted": True})

@router.post("/doctors/{doctor_id}/documents", response_model=APIResponse[DoctorProfileResponse])
async def upload_doctor_document(
    doctor_id: str,
    req: DoctorVerificationDocSchema,
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    doc = await service.add_verification_document(doctor_id, req, payload["sub"])
    return APIResponse(success=True, message="Verification document uploaded", data=doc)

@router.post("/doctors/{doctor_id}/verify", response_model=APIResponse[DoctorProfileResponse])
async def verify_doctor(
    doctor_id: str,
    req: VerifyDoctorRequest,
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    doc = await service.verify_doctor(doctor_id, req, payload["sub"])
    return APIResponse(success=True, message=f"Doctor verification status updated to {req.status.value}", data=doc)

@router.put("/doctors/{doctor_id}/status", response_model=APIResponse[DoctorProfileResponse])
async def update_doctor_active_status(
    doctor_id: str,
    req: UpdateDoctorStatusRequest,
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    doc = await service.update_doctor_active_status(doctor_id, req, payload["sub"])
    return APIResponse(success=True, message="Doctor active status updated", data=doc)

@router.get("/dashboard/stats", response_model=APIResponse[AdminDashboardStats])
async def get_dashboard_stats(
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    stats = await service.get_dashboard_stats()
    return APIResponse(success=True, message="Dashboard statistics retrieved", data=stats)

@router.get("/audit-logs", response_model=APIResponse[PaginatedResponse[AuditLogEntry]])
async def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    payload: dict = Depends(require_admin_role),
    service: AdminService = Depends(get_admin_service)
):
    pagination = PaginationParams(page=page, limit=limit)
    logs = await service.get_audit_logs(pagination)
    return APIResponse(success=True, message="Audit logs retrieved", data=logs)
