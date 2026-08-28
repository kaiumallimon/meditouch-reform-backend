from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.consultations.repository import ConsultationRepository
from app.modules.appointments.repository import AppointmentRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.consultations.service import ConsultationService
from app.modules.consultations.schemas import (
    VideoRoomTokenResponse,
    CompleteConsultationRequest,
    ConsultationRecordResponse
)
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload
from app.common.enums import UserRole
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/consultations", tags=["Consultations & ZEGOCLOUD Video"])

def get_consultation_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> ConsultationService:
    repo = ConsultationRepository(db)
    apt_repo = AppointmentRepository(db)
    doc_repo = DoctorRepository(db)
    return ConsultationService(repo, apt_repo, doc_repo, db)

@router.post("/{appointment_id}/token", response_model=APIResponse[VideoRoomTokenResponse])
async def get_video_token(
    appointment_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: ConsultationService = Depends(get_consultation_service)
):
    token_resp = await service.get_video_room_token(
        appointment_id=appointment_id,
        user_id=payload["sub"],
        user_role=payload.get("role", "")
    )
    return APIResponse(success=True, message="Video room token authorized", data=token_resp)

@router.post("/{appointment_id}/complete", response_model=APIResponse[ConsultationRecordResponse])
async def complete_consultation(
    appointment_id: str,
    req: CompleteConsultationRequest,
    payload: dict = Depends(get_current_user_payload),
    service: ConsultationService = Depends(get_consultation_service)
):
    if payload.get("role") != UserRole.DOCTOR.value:
        raise ForbiddenException("Only DOCTOR can complete a consultation")
    record = await service.complete_consultation(appointment_id, payload["sub"], req)
    return APIResponse(success=True, message="Consultation completed and prescription saved", data=record)

@router.get("/{appointment_id}", response_model=APIResponse[ConsultationRecordResponse])
async def get_consultation_record(
    appointment_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: ConsultationService = Depends(get_consultation_service)
):
    record = await service.get_consultation_record(
        appointment_id=appointment_id,
        user_id=payload["sub"],
        user_role=payload.get("role", "")
    )
    return APIResponse(success=True, message="Consultation record retrieved", data=record)

