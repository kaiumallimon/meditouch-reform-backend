from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.modules.appointments.repository import AppointmentRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.payments.service import PaymentService
from app.modules.payments.repository import PaymentRepository
from app.modules.appointments.schemas import (
    BookAppointmentRequest,
    FeeBreakdownResponse,
    AppointmentResponse
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.enums import (
    AppointmentStatus,
    TimeslotStatus,
    PaymentTargetType,
    UserRole,
    AuditAction
)
from app.common.utils import calculate_fee_breakdown, generate_invoice_number
from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    BadRequestException,
    SlotAlreadyBookedException
)
from app.core.logging import log_audit_event

def is_appointment_joinable(start_time: datetime, end_time: datetime) -> bool:
    now = datetime.now(timezone.utc)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    window_start = start_time - timedelta(minutes=settings.APPOINTMENT_JOINABLE_WINDOW_BEFORE_MINUTES)
    window_end = end_time + timedelta(minutes=settings.APPOINTMENT_JOINABLE_WINDOW_AFTER_MINUTES)
    return window_start <= now <= window_end

class AppointmentService:
    def __init__(
        self,
        repo: AppointmentRepository,
        doctor_repo: DoctorRepository,
        payment_service: PaymentService,
        db: AsyncIOMotorDatabase
    ):
        self.repo = repo
        self.doctor_repo = doctor_repo
        self.payment_service = payment_service
        self.db = db

    async def get_fee_breakdown(self, doctor_id: str) -> FeeBreakdownResponse:
        doctor = await self.doctor_repo.get_by_id(doctor_id)
        if not doctor or not doctor.get("is_active", False):
            raise NotFoundException("Doctor not found or inactive")

        doctor_fee = float(doctor.get("consultation_fee", 0.0))
        doc_fee, plat_fee, total = calculate_fee_breakdown(doctor_fee, settings.PLATFORM_FEE_PERCENTAGE)

        return FeeBreakdownResponse(
            doctor_fee=doc_fee,
            platform_fee=plat_fee,
            platform_fee_percent=settings.PLATFORM_FEE_PERCENTAGE,
            total_amount=total,
            currency="BDT"
        )

    async def book_appointment(self, patient_user_id: str, req: BookAppointmentRequest) -> AppointmentResponse:
        patient_user = await self.db.users.find_one({"id": patient_user_id})
        if not patient_user:
            raise NotFoundException("Patient user not found")

        doctor = await self.doctor_repo.get_by_id(req.doctor_id)
        if not doctor or not doctor.get("is_active", False):
            raise NotFoundException("Doctor not found or currently inactive")

        slot = await self.doctor_repo.reserve_timeslot_atomic(req.timeslot_id)
        if not slot:
            raise SlotAlreadyBookedException("This timeslot is no longer available. Please select another slot.")

        doctor_fee = float(doctor.get("consultation_fee", 0.0))
        doc_fee, plat_fee, total = calculate_fee_breakdown(doctor_fee, settings.PLATFORM_FEE_PERCENTAGE)

        invoice_number = generate_invoice_number(prefix="APT")
        appointment_doc = {
            "patient_id": patient_user_id,
            "patient_name": patient_user.get("name", "Patient"),
            "patient_phone": patient_user.get("phone", ""),
            "doctor_id": doctor["id"],
            "doctor_name": doctor.get("name", "Doctor"),
            "doctor_specialties": doctor.get("specialties", []),
            "timeslot_id": slot["id"],
            "start_time": slot["start_time"],
            "end_time": slot["end_time"],
            "doctor_fee": doc_fee,
            "platform_fee": plat_fee,
            "total_amount": total,
            "status": AppointmentStatus.PENDING_PAYMENT.value,
            "merchant_invoice_number": invoice_number,
            "patient_notes": req.patient_notes,
            "symptoms": req.symptoms or []
        }

        created = await self.repo.create(appointment_doc)

        try:
            payment_res = await self.payment_service.initiate_payment(
                user_id=patient_user_id,
                payer_phone=patient_user.get("phone", "01700000000"),
                amount=total,
                target_type=PaymentTargetType.APPOINTMENT,
                target_id=created["id"],
                merchant_invoice_number=invoice_number
            )

            await self.db.appointments.update_one(
                {"id": created["id"]},
                {"$set": {"payment_id": payment_res.payment_id, "payment_url": payment_res.bkash_url}}
            )
            created["payment_id"] = payment_res.payment_id
            created["payment_url"] = payment_res.bkash_url
        except Exception as e:
            await self.doctor_repo.release_timeslot_atomic(slot["id"])
            await self.repo.update_status(created["id"], AppointmentStatus.CANCELLED)
            raise BadRequestException(f"Failed to initialize payment gateway: {str(e)}")

        await log_audit_event(
            self.db,
            user_id=patient_user_id,
            action=AuditAction.APPOINTMENT_BOOKED,
            target_type="APPOINTMENT",
            target_id=created["id"],
            details={"doctor_id": doctor["id"], "total_amount": total}
        )

        return self._format_appointment_response(created)

    async def get_patient_appointments(
        self,
        patient_id: str,
        status: Optional[AppointmentStatus],
        pagination: PaginationParams
    ) -> PaginatedResponse[AppointmentResponse]:
        docs, total = await self.repo.get_patient_appointments(
            patient_id=patient_id,
            status=status,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [self._format_appointment_response(d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_doctor_appointments(
        self,
        doctor_user_id: str,
        status: Optional[AppointmentStatus],
        pagination: PaginationParams
    ) -> PaginatedResponse[AppointmentResponse]:
        doc_profile = await self.doctor_repo.get_by_user_id(doctor_user_id)
        if not doc_profile:
            raise NotFoundException("Doctor profile not found")

        docs, total = await self.repo.get_doctor_appointments(
            doctor_id=doc_profile["id"],
            status=status,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [self._format_appointment_response(d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_appointment_by_id(
        self,
        appointment_id: str,
        user_id: str,
        user_role: str
    ) -> AppointmentResponse:
        apt = await self.repo.get_by_id(appointment_id)
        if not apt:
            raise NotFoundException("Appointment not found")

        if user_role == UserRole.ADMIN.value:
            return self._format_appointment_response(apt)

        if apt.get("patient_id") == user_id:
            return self._format_appointment_response(apt)

        doc_profile = await self.doctor_repo.get_by_user_id(user_id)
        if doc_profile and doc_profile["id"] == apt.get("doctor_id"):
            return self._format_appointment_response(apt)

        raise ForbiddenException("You are not authorized to view this appointment")

    async def cancel_appointment(self, appointment_id: str, user_id: str) -> AppointmentResponse:
        apt = await self.repo.get_by_id(appointment_id)
        if not apt:
            raise NotFoundException("Appointment not found")

        if apt.get("patient_id") != user_id:
            raise ForbiddenException("Only the booking patient can cancel this appointment")

        if apt.get("status") not in [AppointmentStatus.PENDING_PAYMENT.value, AppointmentStatus.CONFIRMED.value]:
            raise BadRequestException(f"Cannot cancel appointment with status {apt.get('status')}")

        if apt.get("timeslot_id"):
            await self.doctor_repo.release_timeslot_atomic(apt["timeslot_id"])

        updated = await self.repo.update_status(appointment_id, AppointmentStatus.CANCELLED)

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.APPOINTMENT_CANCELLED,
            target_type="APPOINTMENT",
            target_id=appointment_id
        )

        return self._format_appointment_response(updated)

    def _format_appointment_response(self, apt: Dict[str, Any]) -> AppointmentResponse:
        start_time = apt.get("start_time")
        end_time = apt.get("end_time")
        
        is_joinable = False
        if apt.get("status") == AppointmentStatus.CONFIRMED.value and start_time and end_time:
            is_joinable = is_appointment_joinable(start_time, end_time)

        return AppointmentResponse(
            id=apt["id"],
            patient_id=apt["patient_id"],
            patient_name=apt.get("patient_name", ""),
            patient_phone=apt.get("patient_phone", ""),
            doctor_id=apt["doctor_id"],
            doctor_name=apt.get("doctor_name", ""),
            doctor_specialties=apt.get("doctor_specialties", []),
            timeslot_id=apt["timeslot_id"],
            start_time=start_time,
            end_time=end_time,
            doctor_fee=apt.get("doctor_fee", 0.0),
            platform_fee=apt.get("platform_fee", 0.0),
            total_amount=apt.get("total_amount", 0.0),
            status=AppointmentStatus(apt.get("status")),
            payment_id=apt.get("payment_id"),
            merchant_invoice_number=apt.get("merchant_invoice_number"),
            payment_url=apt.get("payment_url"),
            patient_notes=apt.get("patient_notes"),
            symptoms=apt.get("symptoms", []),
            is_joinable=is_joinable,
            created_at=apt.get("created_at")
        )

