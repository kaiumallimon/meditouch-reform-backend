from fastapi import APIRouter, Depends, Query, status
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.service import DoctorService
from app.modules.doctors.schemas import (
    DoctorProfileResponse,
    UpdateDoctorProfileRequest,
    CreateTimeslotRequest,
    BatchCreateTimeslotsRequest,
    TimeslotResponse,
    DoctorFilterParams
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload
from app.common.enums import UserRole
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/doctors", tags=["Doctors & Telemedicine"])

def get_doctor_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> DoctorService:
    repo = DoctorRepository(db)
    return DoctorService(repo)

@router.get("", response_model=APIResponse[PaginatedResponse[DoctorProfileResponse]])
async def search_doctors(
    specialty: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    min_fee: Optional[float] = Query(None),
    max_fee: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    service: DoctorService = Depends(get_doctor_service)
):
    filters = DoctorFilterParams(specialty=specialty, search=search, min_fee=min_fee, max_fee=max_fee)
    pagination = PaginationParams(page=page, limit=limit)
    res = await service.search_doctors(filters, pagination)
    return APIResponse(success=True, message="Doctors retrieved", data=res)

@router.get("/me/profile", response_model=APIResponse[DoctorProfileResponse])
async def get_my_doctor_profile(
    payload: dict = Depends(get_current_user_payload),
    service: DoctorService = Depends(get_doctor_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR role can access this endpoint")
    doc = await service.get_doctor_profile_by_user_id(payload["sub"])
    return APIResponse(success=True, message="Doctor profile retrieved", data=doc)

@router.put("/me/profile", response_model=APIResponse[DoctorProfileResponse])
async def update_my_doctor_profile(
    req: UpdateDoctorProfileRequest,
    payload: dict = Depends(get_current_user_payload),
    service: DoctorService = Depends(get_doctor_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR role can access this endpoint")
    doc = await service.update_my_doctor_profile(payload["sub"], req)
    return APIResponse(success=True, message="Doctor profile updated", data=doc)

@router.post("/me/timeslots", response_model=APIResponse[List[TimeslotResponse]], status_code=status.HTTP_201_CREATED)
async def create_my_timeslots(
    req: BatchCreateTimeslotsRequest,
    payload: dict = Depends(get_current_user_payload),
    service: DoctorService = Depends(get_doctor_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR role can access this endpoint")
    slots = await service.create_doctor_timeslots(payload["sub"], req.slots)
    return APIResponse(success=True, message="Timeslots created successfully", data=slots)

@router.get("/me/timeslots", response_model=APIResponse[List[TimeslotResponse]])
async def get_my_all_timeslots(
    payload: dict = Depends(get_current_user_payload),
    service: DoctorService = Depends(get_doctor_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR role can access this endpoint")
    slots = await service.get_my_all_timeslots(payload["sub"])
    return APIResponse(success=True, message="My timeslots retrieved", data=slots)

@router.delete("/me/timeslots/{timeslot_id}", response_model=APIResponse[dict])
async def delete_my_timeslot(
    timeslot_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: DoctorService = Depends(get_doctor_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR role can access this endpoint")
    await service.delete_my_timeslot(payload["sub"], timeslot_id)
    return APIResponse(success=True, message="Timeslot deleted successfully", data={"id": timeslot_id})

@router.get("/{doctor_id}", response_model=APIResponse[DoctorProfileResponse])
async def get_doctor_by_id(
    doctor_id: str,
    service: DoctorService = Depends(get_doctor_service)
):
    doc = await service.get_doctor_profile_by_id(doctor_id)
    return APIResponse(success=True, message="Doctor profile retrieved", data=doc)

@router.get("/{doctor_id}/timeslots", response_model=APIResponse[List[TimeslotResponse]])
async def get_doctor_available_timeslots(
    doctor_id: str,
    service: DoctorService = Depends(get_doctor_service)
):
    slots = await service.get_doctor_available_timeslots(doctor_id)
    return APIResponse(success=True, message="Available timeslots retrieved", data=slots)

