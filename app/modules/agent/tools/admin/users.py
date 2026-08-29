from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.commands.user_commands import CreateUserCommand, DeactivateUserCommand, DeleteUserCommand
from app.modules.agent.security.confirmation import confirmation_manager
from app.modules.agent.tools.resolver import EntityResolver
from app.modules.admin.repository import AdminRepository
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.admin.service import AdminService
from app.modules.admin.schemas import AdminCreateUserRequest, AdminUpdateUserRequest
from app.common.enums import UserRole

class CreateUserTool(BaseTool):
    name = "create_user"
    description = "Creates a new user account with auto-generated secure password and sends email."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Full name of the user"},
            "phone": {"type": "string", "description": "Primary mobile number (e.g. '+8801711223344')"},
            "email": {"type": "string", "description": "Email address (optional)"},
            "role": {"type": "string", "enum": ["USER", "DOCTOR", "NURSE", "ADMIN"], "default": "USER"},
            "gender": {"type": "string", "enum": ["male", "female", "other", "unspecified"], "default": "unspecified"},
            "address": {"type": "string", "description": "Default delivery/residential address"},
        },
        "required": ["name", "phone"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        admin_repo = AdminRepository(db)
        auth_repo = AuthRepository(db)
        doc_repo = DoctorRepository(db)
        self.service = AdminService(admin_repo, auth_repo, doc_repo, db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        cmd = CreateUserCommand(**arguments)
        req = AdminCreateUserRequest(
            name=cmd.name,
            phone=cmd.phone,
            email=cmd.email,
            role=cmd.role,
            gender=cmd.gender,
            address=cmd.address,
        )

        try:
            user = await self.service.create_user_account(req, admin_id=caller_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result=user.model_dump(),
                metadata={"action": "CREATE_USER", "resource_id": user.id, "user_name": user.name},
            )
        except Exception as e:
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

class DeactivateUserTool(BaseTool):
    name = "deactivate_user"
    description = "Deactivates a user profile. Requires 2-step confirmation."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "User identifier: ID, phone, email, or name"},
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

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        # 1. If confirmation token is provided, execute mutation
        if confirmation_token:
            payload = confirmation_manager.validate_and_consume(confirmation_token, session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid or expired confirmation token")
            
            user_id = payload["target_id"]
            req = AdminUpdateUserRequest(is_active=False)
            user = await self.service.update_user_account(user_id, req, admin_id=caller_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"id": user.id, "name": user.name, "is_active": user.is_active, "status": "DEACTIVATED"},
                metadata={"action": "DEACTIVATE_USER", "resource_id": user.id},
            )

        # 2. Stage 1: Disambiguate and prompt for confirmation
        query = arguments.get("query", "")
        res = await self.resolver.resolve_user(query)
        if res["status"] == "NOT_FOUND":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"No user found matching: {query}")
        elif res["status"] == "AMBIGUOUS":
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"candidates": res["candidates"], "message": f"Multiple users matched '{query}'. Please specify phone or ID."},
            )

        # Exact match found -> Stage confirmation
        target = res["match"]
        token = confirmation_manager.create_pending_confirmation(
            session_id=session_id,
            action="deactivate_user",
            target_type="USER",
            target_id=target["id"],
            target_name=target.get("name"),
            summary=f"Deactivate user {target.get('name')} (Phone: {target.get('phone')}, Role: {target.get('role')})",
            command_data={"user_id": target["id"]},
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={
                "user_id": target["id"],
                "name": target.get("name"),
                "phone": target.get("phone"),
                "role": target.get("role"),
                "current_status": "ACTIVE" if target.get("is_active", True) else "INACTIVE",
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"⚠️ Found user: {target.get('name')} (Phone: {target.get('phone')}, Role: {target.get('role')}). This action will deactivate their account. Confirm?",
        )

class DeleteUserTool(BaseTool):
    name = "delete_user"
    description = "Permanently soft-deletes a user profile. Requires explicit confirmation."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "User ID, phone, email, or name to delete"},
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

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        if confirmation_token:
            payload = confirmation_manager.validate_and_consume(confirmation_token, session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid or expired confirmation token")
            
            user_id = payload["target_id"]
            user = await self.service.soft_delete_user_account(user_id, admin_id=caller_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"id": user.id, "name": user.name, "is_active": user.is_active, "status": "SOFT_DELETED"},
                metadata={"action": "DELETE_USER", "resource_id": user.id},
            )

        query = arguments.get("query", "")
        res = await self.resolver.resolve_user(query)
        if res["status"] == "NOT_FOUND":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"No user found matching: {query}")
        elif res["status"] == "AMBIGUOUS":
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"candidates": res["candidates"], "message": f"Multiple users matched '{query}'. Please specify phone or ID."},
            )

        target = res["match"]
        token = confirmation_manager.create_pending_confirmation(
            session_id=session_id,
            action="delete_user",
            target_type="USER",
            target_id=target["id"],
            target_name=target.get("name"),
            summary=f"Delete user {target.get('name')} (ID: {target['id']})",
            command_data={"user_id": target["id"]},
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={
                "user_id": target["id"],
                "name": target.get("name"),
                "phone": target.get("phone"),
                "role": target.get("role"),
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"🚨 DESTRUCTIVE OPERATION: Delete user '{target.get('name')}' (ID: {target['id']})? Confirm?",
        )
