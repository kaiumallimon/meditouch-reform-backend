from typing import Dict, Any, Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.security.confirmation import confirmation_manager
from app.modules.agent.tools.resolver import EntityResolver
from app.modules.admin.repository import AdminRepository
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.admin.service import AdminService
from app.modules.admin.schemas import CreateDoctorAccountRequest
from app.common.enums import UserRole, DoctorVerificationStatus
import uuid

class CreateDoctorTool(BaseTool):
    name = "create_doctor"
    description = "Registers a new doctor profile with BMDC number, specialties, qualifications, and consultation fee. Requires admin confirmation."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Doctor's full name with title (e.g., 'Dr. Jane Smith')"},
            "phone": {"type": "string", "description": "Doctor's mobile number (e.g. '+8801811223344')"},
            "email": {"type": "string", "description": "Doctor's email address"},
            "bmdc_reg_number": {"type": "string", "description": "BMDC registration number (e.g., 'A-12345')"},
            "specialties": {"type": "array", "items": {"type": "string"}, "description": "Medical specialties (e.g., ['Cardiology', 'General Medicine'])"},
            "qualifications": {"type": "array", "items": {"type": "string"}, "description": "Degrees (e.g., ['MBBS', 'FCPS'])"},
            "consultation_fee": {"type": "number", "description": "Consultation fee in BDT (e.g., 500.0)"},
            "experience_years": {"type": "integer", "description": "Years of clinical experience", "default": 5},
        },
        "required": ["name", "phone", "email", "bmdc_reg_number", "consultation_fee"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        admin_repo = AdminRepository(db)
        auth_repo = AuthRepository(db)
        doc_repo = DoctorRepository(db)
        self.service = AdminService(admin_repo, auth_repo, doc_repo, db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        if confirmation_token:
            payload = confirmation_manager.validate_and_consume(confirmation_token, session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid or expired confirmation token")

            cdata = payload.get("command_data", arguments)
            req = CreateDoctorAccountRequest(
                name=cdata["name"],
                phone=cdata["phone"],
                email=cdata["email"],
                bmdc_reg_number=cdata["bmdc_reg_number"],
                specialties=cdata.get("specialties", ["General Medicine"]),
                qualifications=cdata.get("qualifications", ["MBBS"]),
                consultation_fee=float(cdata["consultation_fee"]),
                experience_years=int(cdata.get("experience_years", 5)),
            )

            try:
                doc = await self.service.create_doctor_account(req, admin_id=caller_id)
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result=doc.model_dump(),
                    metadata={"action": "CREATE_DOCTOR", "doctor_id": doc.id, "doctor_name": doc.name},
                )
            except Exception as e:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        token = confirmation_manager.create_pending_confirmation(
            session_id=session_id,
            action="create_doctor",
            target_type="DOCTOR",
            target_id="new_doctor",
            target_name=arguments["name"],
            summary=f"Register Dr. {arguments['name']} (BMDC: {arguments['bmdc_reg_number']}, Fee: ৳{arguments['consultation_fee']})",
            command_data=arguments,
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={
                "action": "create_doctor",
                "name": arguments["name"],
                "bmdc": arguments["bmdc_reg_number"],
                "specialties": arguments.get("specialties", ["General Medicine"]),
                "consultation_fee": arguments["consultation_fee"],
                "phone": arguments["phone"],
                "email": arguments["email"],
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"Register new doctor '{arguments['name']}' (BMDC: {arguments['bmdc_reg_number']}, Fee: ৳{arguments['consultation_fee']})? Account credentials will be emailed to {arguments['email']}.",
        )

class VerifyDoctorTool(BaseTool):
    name = "verify_doctor"
    description = "Updates the verification status of a doctor account (VERIFIED or REJECTED). Requires admin confirmation."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "doctor_id": {"type": "string", "description": "Doctor's ID or BMDC registration number"},
            "status": {"type": "string", "enum": ["VERIFIED", "REJECTED", "PENDING"], "description": "New verification status"},
            "rejection_reason": {"type": "string", "description": "Optional notes or rejection explanation"},
        },
        "required": ["doctor_id", "status"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        admin_repo = AdminRepository(db)
        auth_repo = AuthRepository(db)
        doc_repo = DoctorRepository(db)
        self.service = AdminService(admin_repo, auth_repo, doc_repo, db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        doctor_id = arguments["doctor_id"].strip()
        status_str = arguments["status"].upper()
        rejection_reason = arguments.get("rejection_reason")

        if confirmation_token:
            payload = confirmation_manager.validate_and_consume(confirmation_token, session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid or expired confirmation token")

            try:
                status_enum = DoctorVerificationStatus(status_str)
                doc = await self.service.verify_doctor(
                    doctor_id=doctor_id,
                    status=status_enum,
                    rejection_reason=rejection_reason,
                    admin_id=caller_id,
                )
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result=doc.model_dump(),
                    metadata={"action": "VERIFY_DOCTOR", "doctor_id": doc.id, "status": status_str},
                )
            except Exception as e:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        token = confirmation_manager.create_pending_confirmation(
            session_id=session_id,
            action="verify_doctor",
            target_type="DOCTOR",
            target_id=doctor_id,
            target_name=doctor_id,
            summary=f"Set doctor {doctor_id} status to {status_str}",
            command_data=arguments,
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={"doctor_id": doctor_id, "new_status": status_str, "reason": rejection_reason},
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"Update verification status of Doctor '{doctor_id}' to {status_str}? Confirm?",
        )

class DeleteDoctorTool(BaseTool):
    name = "delete_doctor"
    description = "Soft-deletes a doctor profile. Requires 2-step confirmation."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Doctor identifier: ID, BMDC number, phone, or name"},
        },
        "required": ["query"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.resolver = EntityResolver(db)
        admin_repo = AdminRepository(db)
        auth_repo = AuthRepository(db)
        doc_repo = DoctorRepository(db)
        self.service = AdminService(admin_repo, auth_repo, doc_repo, db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        if confirmation_token:
            payload = confirmation_manager.validate_and_consume(confirmation_token, session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid or expired confirmation token")
            
            doctor_id = payload["target_id"]
            doc = await self.service.soft_delete_doctor_account(doctor_id, admin_id=caller_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"id": doc.id, "name": doc.name, "status": "DELETED"},
                metadata={"action": "DELETE_DOCTOR", "doctor_id": doc.id},
            )

        query = arguments.get("query", "").strip()
        doc = await self.db.doctors.find_one({"$or": [{"id": query}, {"bmdc_reg_number": query}, {"phone": query}, {"name": {"$regex": query, "$options": "i"}}]})
        if not doc:
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"No doctor found matching: {query}")

        token = confirmation_manager.create_pending_confirmation(
            session_id=session_id,
            action="delete_doctor",
            target_type="DOCTOR",
            target_id=doc["id"],
            target_name=doc.get("name"),
            summary=f"Delete doctor Dr. {doc.get('name')} (BMDC: {doc.get('bmdc_reg_number')})",
            command_data={"doctor_id": doc["id"]},
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={"doctor_id": doc["id"], "name": doc.get("name"), "bmdc": doc.get("bmdc_reg_number")},
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"🚨 DESTRUCTIVE OPERATION: Are you sure you want to delete doctor '{doc.get('name')}' (BMDC: {doc.get('bmdc_reg_number')})? Confirm?",
        )
