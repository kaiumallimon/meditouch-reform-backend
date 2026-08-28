from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
import uuid

from app.modules.consultations.repository import ConsultationRepository
from app.modules.appointments.repository import AppointmentRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.consultations.schemas import (
    VideoRoomTokenResponse,
    CompleteConsultationRequest,
    ConsultationRecordResponse,
    PrescribedMedicationSchema
)
from app.integrations.zegocloud.token_generator import generate_zegocloud_token
from app.common.enums import AppointmentStatus, UserRole, NotificationType, AuditAction
from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    BadRequestException
)
from app.core.logging import logger, log_audit_event

class ConsultationService:
    def __init__(
        self,
        repo: ConsultationRepository,
        appointment_repo: AppointmentRepository,
        doctor_repo: DoctorRepository,
        db: AsyncIOMotorDatabase
    ):
        self.repo = repo
        self.appointment_repo = appointment_repo
        self.doctor_repo = doctor_repo
        self.db = db

    async def get_video_room_token(
        self,
        appointment_id: str,
        user_id: str,
        user_role: str
    ) -> VideoRoomTokenResponse:
        apt = await self.appointment_repo.get_by_id(appointment_id)
        if not apt:
            raise NotFoundException("Appointment not found")

        allowed_statuses = [AppointmentStatus.CONFIRMED.value, AppointmentStatus.IN_PROGRESS.value]
        if apt.get("status") not in allowed_statuses:
            raise BadRequestException(
                f"Cannot join video room. Appointment status is '{apt.get('status')}'. Must be CONFIRMED."
            )

        start_time = apt.get("start_time")
        end_time = apt.get("end_time")
        if start_time and end_time:
            now = datetime.now(timezone.utc)
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)

            window_start = start_time - timedelta(minutes=settings.APPOINTMENT_JOINABLE_WINDOW_BEFORE_MINUTES)
            window_end = end_time + timedelta(minutes=settings.APPOINTMENT_JOINABLE_WINDOW_AFTER_MINUTES)

            if now < window_start:
                minutes_left = int((window_start - now).total_seconds() / 60)
                raise BadRequestException(
                    f"Consultation is not yet joinable. Room opens {settings.APPOINTMENT_JOINABLE_WINDOW_BEFORE_MINUTES} minutes before appointment (in ~{minutes_left} minutes)."
                )
            if now > window_end:
                raise BadRequestException("Consultation time window has ended.")

        is_patient = apt.get("patient_id") == user_id
        doc_profile = await self.doctor_repo.get_by_user_id(user_id)
        is_doctor = doc_profile and doc_profile.get("id") == apt.get("doctor_id")

        if not is_patient and not is_doctor and user_role != UserRole.ADMIN.value:
            raise ForbiddenException("You are not an authorized participant for this consultation room")

        user_doc = await self.db.users.find_one({"id": user_id})
        user_name = user_doc.get("name", "User") if user_doc else "User"

        room_id = f"meditouch_{appointment_id}"

        if apt.get("status") == AppointmentStatus.CONFIRMED.value:
            await self.appointment_repo.update_status(appointment_id, AppointmentStatus.IN_PROGRESS)

        token = generate_zegocloud_token(
            user_id=user_id,
            room_id=room_id,
            expiry_seconds=settings.ZEGOCLOUD_TOKEN_EXPIRY_SECONDS
        )

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.VIDEO_ROOM_TOKEN_ISSUED,
            target_type="CONSULTATION",
            target_id=appointment_id,
            details={"room_id": room_id, "role": user_role}
        )

        return VideoRoomTokenResponse(
            appointment_id=appointment_id,
            room_id=room_id,
            user_id=user_id,
            user_name=user_name,
            app_id=settings.ZEGOCLOUD_APP_ID,
            zego_token=token,
            expires_in_seconds=settings.ZEGOCLOUD_TOKEN_EXPIRY_SECONDS
        )

    async def complete_consultation(
        self,
        appointment_id: str,
        doctor_user_id: str,
        req: CompleteConsultationRequest
    ) -> ConsultationRecordResponse:
        apt = await self.appointment_repo.get_by_id(appointment_id)
        if not apt:
            raise NotFoundException("Appointment not found")

        doc_profile = await self.doctor_repo.get_by_user_id(doctor_user_id)
        if not doc_profile or doc_profile.get("id") != apt.get("doctor_id"):
            raise ForbiddenException("Only the assigned doctor can complete this consultation")

        if apt.get("status") not in [AppointmentStatus.CONFIRMED.value, AppointmentStatus.IN_PROGRESS.value]:
            raise BadRequestException(f"Cannot complete appointment with status '{apt.get('status')}'")

        record_doc = {
            "id": str(uuid.uuid4()),
            "appointment_id": appointment_id,
            "patient_id": apt["patient_id"],
            "patient_name": apt.get("patient_name", "Patient"),
            "doctor_id": doc_profile["id"],
            "doctor_name": doc_profile.get("name", "Doctor"),
            "diagnosis": req.diagnosis,
            "clinical_notes": req.clinical_notes,
            "prescriptions": [p.model_dump() for p in req.prescriptions],
            "follow_up_date": req.follow_up_date,
            "advice": req.advice,
            "completed_at": datetime.now(timezone.utc)
        }

        saved_record = await self.repo.create_or_update_record(record_doc)
        await self.appointment_repo.update_status(appointment_id, AppointmentStatus.COMPLETED)

        await self.db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": apt["patient_id"],
            "type": NotificationType.SYSTEM.value,
            "title": "Prescription Available",
            "message": f"Dr. {doc_profile.get('name')} has completed your consultation and uploaded your prescription.",
            "payload": {"appointment_id": appointment_id},
            "is_read": False,
            "created_at": datetime.now(timezone.utc)
        })

        await log_audit_event(
            self.db,
            user_id=doctor_user_id,
            action=AuditAction.CONSULTATION_COMPLETED,
            target_type="CONSULTATION",
            target_id=appointment_id,
            details={"diagnosis": req.diagnosis}
        )

        return ConsultationRecordResponse(
            id=saved_record["id"],
            appointment_id=saved_record["appointment_id"],
            patient_id=saved_record["patient_id"],
            patient_name=saved_record["patient_name"],
            doctor_id=saved_record["doctor_id"],
            doctor_name=saved_record["doctor_name"],
            diagnosis=saved_record["diagnosis"],
            clinical_notes=saved_record.get("clinical_notes"),
            prescriptions=[PrescribedMedicationSchema(**p) for p in saved_record.get("prescriptions", [])],
            follow_up_date=saved_record.get("follow_up_date"),
            advice=saved_record.get("advice"),
            completed_at=saved_record["completed_at"]
        )

    async def get_consultation_record(
        self,
        appointment_id: str,
        user_id: str,
        user_role: str
    ) -> ConsultationRecordResponse:
        record = await self.repo.get_by_appointment_id(appointment_id)
        if not record:
            raise NotFoundException("Consultation record / prescription not found")

        if user_role != UserRole.ADMIN.value:
            doc_profile = await self.doctor_repo.get_by_user_id(user_id)
            is_doctor = doc_profile and doc_profile.get("id") == record.get("doctor_id")
            is_patient = record.get("patient_id") == user_id
            if not is_patient and not is_doctor:
                raise ForbiddenException("You are not authorized to view this medical record")

        return ConsultationRecordResponse(
            id=record["id"],
            appointment_id=record["appointment_id"],
            patient_id=record["patient_id"],
            patient_name=record["patient_name"],
            doctor_id=record["doctor_id"],
            doctor_name=record["doctor_name"],
            diagnosis=record["diagnosis"],
            clinical_notes=record.get("clinical_notes"),
            prescriptions=[PrescribedMedicationSchema(**p) for p in record.get("prescriptions", [])],
            follow_up_date=record.get("follow_up_date"),
            advice=record.get("advice"),
            completed_at=record["completed_at"]
        )

