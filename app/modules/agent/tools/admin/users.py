from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import ValidationError
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.modules.agent.commands.user_commands import CreateUserCommand
from app.modules.agent.security.pending_actions import AgentPendingActionRepository
from app.modules.agent.tools.resolver import EntityResolver
from app.modules.admin.repository import AdminRepository
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.repository import DoctorRepository
from app.modules.admin.service import AdminService
from app.modules.admin.schemas import AdminCreateUserRequest, AdminUpdateUserRequest
from app.common.enums import UserRole

class SearchUsersTool(BaseTool):
    name = "search_users"
    description = "Searches for user accounts by email, name, phone number, role, or ID in the database. Returns sanitized user profiles."
    capability = ToolCapability.READ_ADMIN_DATA
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search term: email address, full name, phone number, or account ID"},
            "role": {"type": "string", "enum": ["USER", "DOCTOR", "NURSE", "ADMIN", "DEVELOPER"], "description": "Optional filter by user role"},
            "limit": {"type": "integer", "description": "Maximum number of results to return (default: 5)", "default": 5},
        },
        "required": ["query"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.resolver = EntityResolver(db)
        self.admin_repo = AdminRepository(db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        query = arguments.get("query", "").strip()
        role = arguments.get("role")
        limit = min(int(arguments.get("limit", 5)), 20)

        if query:
            res = await self.resolver.resolve_user(query)
            if res["status"] == "EXACT_MATCH":
                u = res["match"]
                sanitized = {
                    "id": u.get("id"),
                    "name": u.get("name"),
                    "email": u.get("email"),
                    "phone": u.get("phone"),
                    "role": u.get("role"),
                    "is_active": u.get("is_active", True),
                    "gender": u.get("gender"),
                    "address": u.get("address"),
                    "created_at": str(u.get("created_at")),
                }
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.SUCCESS, result={"users": [sanitized], "total": 1, "query": query}, metadata={"action": "SEARCH_USERS", "matches": 1})
            elif res["status"] == "AMBIGUOUS":
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.SUCCESS, result={"users": res["candidates"], "total": len(res["candidates"]), "message": "Multiple matches found"}, metadata={"action": "SEARCH_USERS", "matches": len(res["candidates"])})

        users, total = await self.admin_repo.get_all_users_admin(search=query if query else None, role=role, limit=limit)
        sanitized_list = [
            {
                "id": u.get("id"),
                "name": u.get("name"),
                "email": u.get("email"),
                "phone": u.get("phone"),
                "role": u.get("role"),
                "is_active": u.get("is_active", True),
                "gender": u.get("gender"),
                "address": u.get("address"),
                "created_at": str(u.get("created_at")),
            }
            for u in users
        ]
        return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.SUCCESS, result={"users": sanitized_list, "total": total, "query": query}, metadata={"action": "SEARCH_USERS", "matches": len(sanitized_list)})

class CreateUserTool(BaseTool):
    name = "create_user"
    description = "Creates a new user account with auto-generated secure password and sends email. Requires admin confirmation."
    capability = ToolCapability.CREATE_USER
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = True
    is_destructive = False
    requires_confirmation = True
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
        self.pending_repo = AgentPendingActionRepository(db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        # 1. Pydantic Command Validation
        try:
            cmd = CreateUserCommand(**arguments)
        except ValidationError as ve:
            errors = [f"{e['loc'][0]}: {e['msg']}" for e in ve.errors()]
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"Validation failed: {'; '.join(errors)}")
        except Exception as e:
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        # 2. Execution with Verified Pending Action
        if confirmation_token:
            payload = await self.pending_repo.validate_and_consume(confirmation_token, actor_id=caller_id, session_id=session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid, expired, or already executed confirmation token.")

            cdata = payload.get("command_data", arguments)
            req = AdminCreateUserRequest(
                name=cdata["name"],
                phone=cdata["phone"],
                email=cdata.get("email"),
                role=cdata.get("role", "USER"),
                gender=cdata.get("gender", "unspecified"),
                address=cdata.get("address"),
            )
            try:
                user = await self.service.create_user_account(req, admin_id=caller_id)
                await self.pending_repo.mark_completed(confirmation_token, {"created_user_id": user.id})
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result=user.model_dump(),
                    metadata={"action": "CREATE_USER", "resource_id": user.id, "user_name": user.name},
                )
            except Exception as e:
                await self.pending_repo.mark_failed(confirmation_token, str(e))
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        # 3. Request Admin Confirmation
        token = await self.pending_repo.create_pending_action(
            actor_id=caller_id,
            actor_role=caller_role,
            session_id=session_id,
            action="create_user",
            target_type="USER",
            target_id="new_user",
            target_name=cmd.name,
            summary=f"Create {cmd.role} account for {cmd.name} (Phone: {cmd.phone}, Email: {cmd.email or 'N/A'})",
            command_data=arguments,
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={
                "action": "create_user",
                "name": cmd.name,
                "phone": cmd.phone,
                "email": cmd.email,
                "role": cmd.role,
                "gender": cmd.gender,
                "address": cmd.address,
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"Create new {cmd.role} account for '{cmd.name}' (Phone: {cmd.phone}, Email: {cmd.email or 'N/A'})? Credentials will be auto-generated and emailed.",
        )

class DeactivateUserTool(BaseTool):
    name = "deactivate_user"
    description = "Deactivates a user profile. Requires 2-step confirmation."
    capability = ToolCapability.DEACTIVATE_PROFILE
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = True
    is_destructive = True
    requires_confirmation = True
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
        self.pending_repo = AgentPendingActionRepository(db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        if confirmation_token:
            payload = await self.pending_repo.validate_and_consume(confirmation_token, actor_id=caller_id, session_id=session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid, expired, or already executed confirmation token.")
            
            user_id = payload["target_id"]
            try:
                req = AdminUpdateUserRequest(is_active=False)
                user = await self.service.update_user_account(user_id, req, admin_id=caller_id)
                await self.pending_repo.mark_completed(confirmation_token, {"user_id": user.id, "status": "DEACTIVATED"})
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result={"id": user.id, "name": user.name, "is_active": user.is_active, "status": "DEACTIVATED"},
                    metadata={"action": "DEACTIVATE_USER", "resource_id": user.id},
                )
            except Exception as e:
                await self.pending_repo.mark_failed(confirmation_token, str(e))
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

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
        token = await self.pending_repo.create_pending_action(
            actor_id=caller_id,
            actor_role=caller_role,
            session_id=session_id,
            action="deactivate_user",
            target_type="USER",
            target_id=target["id"],
            target_name=target.get("name"),
            summary=f"Deactivate user {target.get('name')} (ID: {target['id']})",
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
                "current_status": "Active" if target.get("is_active", True) else "Inactive",
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"🚨 DESTRUCTIVE OPERATION: Deactivate user '{target.get('name')}' (Phone: {target.get('phone')}, ID: {target['id']})? Confirm?",
        )

class DeleteUserTool(BaseTool):
    name = "delete_user"
    description = "Soft-deletes a user profile. Requires 2-step confirmation."
    capability = ToolCapability.DELETE_PROFILE
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = True
    is_destructive = True
    requires_confirmation = True
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
        self.pending_repo = AgentPendingActionRepository(db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        if confirmation_token:
            payload = await self.pending_repo.validate_and_consume(confirmation_token, actor_id=caller_id, session_id=session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid, expired, or already executed confirmation token.")
            
            user_id = payload["target_id"]
            try:
                user = await self.service.soft_delete_user_account(user_id, admin_id=caller_id)
                await self.pending_repo.mark_completed(confirmation_token, {"user_id": user.id, "status": "SOFT_DELETED"})
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result={"id": user.id, "name": user.name, "is_active": user.is_active, "status": "SOFT_DELETED"},
                    metadata={"action": "DELETE_USER", "resource_id": user.id},
                )
            except Exception as e:
                await self.pending_repo.mark_failed(confirmation_token, str(e))
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

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
        token = await self.pending_repo.create_pending_action(
            actor_id=caller_id,
            actor_role=caller_role,
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
