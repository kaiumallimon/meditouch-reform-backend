from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.doctors.repository import DoctorRepository
from app.modules.doctors.service import DoctorService
from app.modules.doctors.schemas import DoctorFilterParams
from app.common.pagination import PaginationParams
from app.common.enums import UserRole

class SearchDoctorsTool(BaseTool):
    name = "search_doctors"
    description = "Searches verified telemedicine doctors by specialty, name, or hospital."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    parameters = {
        "type": "object",
        "properties": {
            "specialty": {"type": "string", "description": "Medical specialty (e.g. 'Cardiology', 'General Medicine', 'Dermatology')"},
            "search": {"type": "string", "description": "Doctor name keyword"},
            "limit": {"type": "integer", "description": "Max results (default 5)", "default": 5},
        },
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        repo = DoctorRepository(db)
        self.service = DoctorService(repo)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        specialty = arguments.get("specialty")
        search = arguments.get("search")
        limit = min(arguments.get("limit", 5), 10)

        filters = DoctorFilterParams(specialty=specialty, search=search)
        pagination = PaginationParams(page=1, limit=limit)
        res = await self.service.search_doctors(filters, pagination)

        docs = [
            {
                "id": d.id,
                "name": d.name,
                "specialty": d.specialty,
                "degrees": d.degrees,
                "bmdc_number": d.bmdc_number,
                "hospital_affiliation": d.hospital_affiliation,
                "consultation_fee": d.consultation_fee,
                "rating": d.rating,
                "avatar_url": d.avatar_url,
                "is_available_for_telemedicine": d.is_available_for_telemedicine,
            }
            for d in res.items
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={"count": len(docs), "doctors": docs},
            metadata={"count": len(docs)},
        )

class GetDoctorDetailsTool(BaseTool):
    name = "get_doctor_details"
    description = "Retrieves complete clinical profile and available consultation timeslots for a doctor."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    parameters = {
        "type": "object",
        "properties": {
            "doctor_id": {"type": "string", "description": "Doctor profile ID"},
        },
        "required": ["doctor_id"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        repo = DoctorRepository(db)
        self.service = DoctorService(repo)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        doc_id = arguments.get("doctor_id", "").strip()
        try:
            profile = await self.service.get_doctor_profile_by_id(doc_id)
            slots = await self.service.get_doctor_available_timeslots(doc_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={
                    "doctor": profile.model_dump(),
                    "available_slots": [s.model_dump() for s in slots],
                },
            )
        except Exception as e:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message=str(e),
            )
