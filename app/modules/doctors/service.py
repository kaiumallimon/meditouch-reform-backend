from typing import List, Optional
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.schemas import (
    DoctorProfileResponse,
    UpdateDoctorProfileRequest,
    CreateTimeslotRequest,
    TimeslotResponse,
    DoctorFilterParams
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.enums import TimeslotStatus, DoctorVerificationStatus, AuditAction
from app.core.exceptions import NotFoundException, ForbiddenException, BadRequestException, ConflictException
from app.core.logging import log_audit_event

class DoctorService:
    def __init__(self, repo: DoctorRepository, db: Optional[AsyncIOMotorDatabase] = None):
        self.repo = repo
        self.db = db if db is not None else repo.db

    async def get_doctor_profile_by_user_id(self, user_id: str) -> DoctorProfileResponse:
        doc = await self.repo.get_by_user_id(user_id)
        if not doc:
            raise NotFoundException("Doctor profile not found")
        return DoctorProfileResponse(**doc)

    async def get_doctor_profile_by_id(self, doctor_id: str) -> DoctorProfileResponse:
        doc = await self.repo.get_by_id(doctor_id)
        if not doc:
            raise NotFoundException("Doctor not found")
        doc_copy = doc.copy()
        doc_copy.pop("verification_documents", None)
        return DoctorProfileResponse(**doc_copy)

    async def update_my_doctor_profile(self, user_id: str, req: UpdateDoctorProfileRequest) -> DoctorProfileResponse:
        doc = await self.repo.get_by_user_id(user_id)
        if not doc:
            raise NotFoundException("Doctor profile not found")

        updates = {}
        if req.bio is not None:
            updates["bio"] = req.bio
        if req.specialties is not None:
            updates["specialties"] = req.specialties
        if req.qualifications is not None:
            updates["qualifications"] = req.qualifications
        if req.experience_years is not None:
            updates["experience_years"] = req.experience_years
        if req.consultation_fee is not None:
            updates["consultation_fee"] = req.consultation_fee

        updated = await self.repo.update_doctor_profile(doc["id"], updates)

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.DOCTOR_PROFILE_UPDATED,
            target_type="DOCTOR",
            target_id=doc["id"],
            details={"updated_fields": list(updates.keys())}
        )

        return DoctorProfileResponse(**updated)

    async def search_doctors(self, filters: DoctorFilterParams, pagination: PaginationParams) -> PaginatedResponse[DoctorProfileResponse]:
        docs, total = await self.repo.search_doctors(
            specialty=filters.specialty,
            search=filters.search,
            min_fee=filters.min_fee,
            max_fee=filters.max_fee,
            only_active_verified=True,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [DoctorProfileResponse(**d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def create_doctor_timeslots(self, user_id: str, slots: List[CreateTimeslotRequest]) -> List[TimeslotResponse]:
        doc = await self.repo.get_by_user_id(user_id)
        if not doc:
            raise NotFoundException("Doctor profile not found")

        if not doc.get("is_verified", False) or not doc.get("is_active", False):
            raise ForbiddenException("Doctor is not yet verified or active to create consultation timeslots")

        created_slots = []
        now = datetime.now(timezone.utc)

        for slot_req in slots:
            if slot_req.start_time >= slot_req.end_time:
                raise BadRequestException(f"Slot start time ({slot_req.start_time}) must be before end time ({slot_req.end_time})")
            
            if slot_req.start_time <= now:
                raise BadRequestException("Cannot create timeslots in the past")

            slot_doc = {
                "doctor_id": doc["id"],
                "start_time": slot_req.start_time,
                "end_time": slot_req.end_time,
            }
            try:
                saved = await self.repo.create_timeslot(slot_doc)
                created_slots.append(TimeslotResponse(**saved))
            except Exception as e:
                raise ConflictException(f"A timeslot starting at {slot_req.start_time} already exists for this doctor")

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.TIMESLOTS_CREATED,
            target_type="TIMESLOT",
            target_id=doc["id"],
            details={"slots_count": len(created_slots)}
        )

        return created_slots

    async def get_doctor_available_timeslots(self, doctor_id: str) -> List[TimeslotResponse]:
        doc = await self.repo.get_by_id(doctor_id)
        if not doc or not doc.get("is_active", False):
            raise NotFoundException("Active doctor not found")

        now = datetime.now(timezone.utc)
        slots = await self.repo.get_doctor_timeslots(
            doctor_id=doctor_id,
            status=TimeslotStatus.AVAILABLE,
            start_time_gte=now
        )
        return [TimeslotResponse(**s) for s in slots]

    async def get_my_all_timeslots(self, user_id: str) -> List[TimeslotResponse]:
        doc = await self.repo.get_by_user_id(user_id)
        if not doc:
            raise NotFoundException("Doctor profile not found")

        slots = await self.repo.get_doctor_timeslots(doctor_id=doc["id"])
        return [TimeslotResponse(**s) for s in slots]

    async def delete_my_timeslot(self, user_id: str, timeslot_id: str) -> bool:
        doc = await self.repo.get_by_user_id(user_id)
        if not doc:
            raise NotFoundException("Doctor profile not found")

        deleted = await self.repo.delete_timeslot(timeslot_id, doc["id"])
        if not deleted:
            raise BadRequestException("Cannot delete timeslot: slot not found or not in AVAILABLE state")

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.TIMESLOT_DELETED,
            target_type="TIMESLOT",
            target_id=timeslot_id
        )

        return True
