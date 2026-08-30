from typing import Dict, List, Optional, Any, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.tools.user.medicines import SearchMedicinesTool, GetMedicineDetailsTool, CheckMedicineStockTool
from app.modules.agent.tools.user.clinical import AssessSymptomSafetyTool
from app.modules.agent.tools.user.clarification import RequestClarificationTool
from app.modules.agent.tools.user.doctors import SearchDoctorsTool, GetDoctorDetailsTool
from app.modules.agent.tools.user.account import GetMyProfileTool, GetMyOrdersTool, GetMyAppointmentsTool

from app.modules.agent.tools.admin.users import SearchUsersTool, CreateUserTool, DeactivateUserTool, DeleteUserTool
from app.modules.agent.tools.admin.doctors import CreateDoctorTool, VerifyDoctorTool, DeleteDoctorTool
from app.modules.agent.tools.admin.medicines import CreateMedicineTool, UpdateMedicineStockTool, DeleteMedicineTool
from app.modules.agent.tools.admin.stats import GetPlatformSummaryStatsTool, QueryAuditLogsTool, GetAdminOrdersTool
from app.modules.agent.tools.admin.cdn import GetCDNStorageStatsTool
from app.modules.agent.schemas.chat import SessionType
from app.modules.agent.security.policy import ToolPolicyGuard, CallerContext
from app.common.enums import UserRole

class ToolRegistry:
    """
    Central tool registry enforcing the Capability and RBAC Permission Matrix.
    Dynamically returns tool definitions for context and authorizes executions at runtime.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        # 1. Clinical Triage & Safe Catalog Tools (USER, DOCTOR, NURSE, ADMIN)
        self.register(AssessSymptomSafetyTool(self.db))
        self.register(RequestClarificationTool(self.db))
        self.register(SearchMedicinesTool(self.db))
        self.register(GetMedicineDetailsTool(self.db))
        self.register(CheckMedicineStockTool(self.db))
        self.register(SearchDoctorsTool(self.db))
        self.register(GetDoctorDetailsTool(self.db))
        self.register(GetMyProfileTool(self.db))
        self.register(GetMyOrdersTool(self.db))
        self.register(GetMyAppointmentsTool(self.db))

        # 2. Admin User Management Tools (ADMIN, DEVELOPER)
        self.register(SearchUsersTool(self.db))
        self.register(CreateUserTool(self.db))
        self.register(DeactivateUserTool(self.db))
        self.register(DeleteUserTool(self.db))

        # 3. Admin Doctor Management Tools (ADMIN, DEVELOPER)
        self.register(CreateDoctorTool(self.db))
        self.register(VerifyDoctorTool(self.db))
        self.register(DeleteDoctorTool(self.db))

        # 4. Admin Medicine Catalog Tools (ADMIN, DEVELOPER)
        self.register(CreateMedicineTool(self.db))
        self.register(UpdateMedicineStockTool(self.db))
        self.register(DeleteMedicineTool(self.db))

        # 5. Admin Analytics, Audit & CDN Tools (ADMIN, DEVELOPER)
        self.register(GetPlatformSummaryStatsTool(self.db))
        self.register(QueryAuditLogsTool(self.db))
        self.register(GetAdminOrdersTool(self.db))
        self.register(GetCDNStorageStatsTool(self.db))

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_tools_for_context(self, role: str, session_type: SessionType = SessionType.USER) -> List[BaseTool]:
        """Returns tools permitted for the specific role and session context."""
        tools = []
        is_admin_user = role in [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
        
        for t in self._tools.values():
            if not t.is_authorized(role):
                continue
            # If session is USER mode, only include non-admin / non-mutation tools
            if session_type == SessionType.USER and (t.is_mutation or t.is_destructive or not t.is_authorized(UserRole.USER.value)):
                if not is_admin_user:
                    continue
            tools.append(t)
        return tools

    def get_tools_for_role(self, role: str) -> List[BaseTool]:
        """Convenience method returning tools for a role."""
        return self.get_tools_for_context(
            role,
            SessionType.ADMIN if role in [UserRole.ADMIN.value, UserRole.DEVELOPER.value] else SessionType.USER
        )

    def get_schemas_for_context(self, role: str, session_type: SessionType = SessionType.USER) -> List[Dict[str, Any]]:
        return [t.to_openai_schema() for t in self.get_tools_for_context(role, session_type)]

    def get_schemas_for_role(self, role: str) -> List[Dict[str, Any]]:
        """Backward compatibility for existing callers."""
        return self.get_schemas_for_context(role, SessionType.ADMIN if role in [UserRole.ADMIN.value, UserRole.DEVELOPER.value] else SessionType.USER)

    def authorize_execution(self, tool: BaseTool, context: CallerContext) -> Tuple[bool, Optional[str]]:
        """Re-evaluates security policy at tool execution time."""
        return ToolPolicyGuard.authorize_execution(
            tool_name=tool.name,
            capability=tool.capability,
            roles_allowed=tool.roles_allowed,
            is_mutation=tool.is_mutation,
            is_destructive=tool.is_destructive,
            context=context,
        )
