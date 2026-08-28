from fastapi import APIRouter, Depends, Query, status
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.appointments.repository import AppointmentRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.payments.repository import PaymentRepository
from app.modules.payments.service import PaymentService
from app.modules.appointments.service import AppointmentService
from app.modules.appointments.schemas import (
    BookAppointmentRequest,
    FeeBreakdownResponse,
    AppointmentResponse
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.responses import APIResponse
from app.common.enums import AppointmentStatus, UserRole
from app.core.security import get_current_user_payload
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/appointments", tags=["Appointments & Telemedicine"])

def get_appointment_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> AppointmentService:
    apt_repo = AppointmentRepository(db)
    doc_repo = DoctorRepository(db)
    pay_repo = PaymentRepository(db)
    pay_service = PaymentService(pay_repo, db)
    return AppointmentService(apt_repo, doc_repo, pay_service, db)

@router.get("/fee-breakdown/{doctor_id}", response_model=APIResponse[FeeBreakdownResponse])
async def get_fee_breakdown(
    doctor_id: str,
    service: AppointmentService = Depends(get_appointment_service)
):
    fee = await service.get_fee_breakdown(doctor_id)
    return APIResponse(success=True, message="Fee breakdown calculated", data=fee)

@router.post("/book", response_model=APIResponse[AppointmentResponse], status_code=status.HTTP_201_CREATED)
async def book_appointment(
    req: BookAppointmentRequest,
    payload: dict = Depends(get_current_user_payload),
    service: AppointmentService = Depends(get_appointment_service)
):
    apt = await service.book_appointment(payload["sub"], req)
    return APIResponse(success=True, message="Appointment created. Complete payment to confirm.", data=apt)

@router.get("/my-appointments", response_model=APIResponse[PaginatedResponse[AppointmentResponse]])
async def get_patient_appointments(
    status: Optional[AppointmentStatus] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(get_current_user_payload),
    service: AppointmentService = Depends(get_appointment_service)
):
    pagination = PaginationParams(page=page, limit=limit)
    res = await service.get_patient_appointments(payload["sub"], status, pagination)
    return APIResponse(success=True, message="Patient appointments retrieved", data=res)

@router.get("/doctor-appointments", response_model=APIResponse[PaginatedResponse[AppointmentResponse]])
async def get_doctor_appointments(
    status: Optional[AppointmentStatus] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(get_current_user_payload),
    service: AppointmentService = Depends(get_appointment_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR can access doctor appointments")
    pagination = PaginationParams(page=page, limit=limit)
    res = await service.get_doctor_appointments(payload["sub"], status, pagination)
    return APIResponse(success=True, message="Doctor appointments retrieved", data=res)

@router.get("/{appointment_id}", response_model=APIResponse[AppointmentResponse])
async def get_appointment(
    appointment_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: AppointmentService = Depends(get_appointment_service)
):
    apt = await service.get_appointment_by_id(appointment_id, payload["sub"], payload.get("role", ""))
    return APIResponse(success=True, message="Appointment details retrieved", data=apt)

@router.post("/{appointment_id}/cancel", response_model=APIResponse[AppointmentResponse])
async def cancel_appointment(
    appointment_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: AppointmentService = Depends(get_appointment_service)
):
    apt = await service.cancel_appointment(appointment_id, payload["sub"])
    return APIResponse(success=True, message="Appointment cancelled successfully", data=apt)

