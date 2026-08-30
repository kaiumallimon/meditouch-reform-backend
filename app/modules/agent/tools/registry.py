from typing import Dict, List, Optional, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.tools.user.medicines import SearchMedicinesTool, GetMedicineDetailsTool, CheckMedicineStockTool
from app.modules.agent.tools.user.clinical import SuggestMedicinesForSymptomsTool
from app.modules.agent.tools.user.doctors import SearchDoctorsTool, GetDoctorDetailsTool
from app.modules.agent.tools.user.account import GetMyProfileTool, GetMyOrdersTool, GetMyAppointmentsTool

from app.modules.agent.tools.admin.users import SearchUsersTool, CreateUserTool, DeactivateUserTool, DeleteUserTool
from app.modules.agent.tools.admin.doctors import CreateDoctorTool, VerifyDoctorTool, DeleteDoctorTool
from app.modules.agent.tools.admin.medicines import CreateMedicineTool, UpdateMedicineStockTool, DeleteMedicineTool
from app.modules.agent.tools.admin.stats import GetPlatformSummaryStatsTool, QueryAuditLogsTool, GetAdminOrdersTool
from app.modules.agent.tools.admin.cdn import GetCDNStorageStatsTool
from app.common.enums import UserRole

class ToolRegistry:
    """
    Central tool registry enforcing the Tool Permission Matrix.
    Dynamically returns tool definitions and dispatches executions according to caller role.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        # 1. User / Patient / General Read Tools
        self.register(SearchMedicinesTool(self.db))
        self.register(GetMedicineDetailsTool(self.db))
        self.register(CheckMedicineStockTool(self.db))
        self.register(SuggestMedicinesForSymptomsTool(self.db))
        self.register(SearchDoctorsTool(self.db))
        self.register(GetDoctorDetailsTool(self.db))
        self.register(GetMyProfileTool(self.db))
        self.register(GetMyOrdersTool(self.db))
        self.register(GetMyAppointmentsTool(self.db))

        # 2. Admin User Management Tools
        self.register(SearchUsersTool(self.db))
        self.register(CreateUserTool(self.db))
        self.register(DeactivateUserTool(self.db))
        self.register(DeleteUserTool(self.db))

        # 3. Admin Doctor Management Tools
        self.register(CreateDoctorTool(self.db))
        self.register(VerifyDoctorTool(self.db))
        self.register(DeleteDoctorTool(self.db))

        # 4. Admin Medicine Catalog Tools
        self.register(CreateMedicineTool(self.db))
        self.register(UpdateMedicineStockTool(self.db))
        self.register(DeleteMedicineTool(self.db))

        # 5. Admin Analytics, Audit & CDN Tools
        self.register(GetPlatformSummaryStatsTool(self.db))
        self.register(QueryAuditLogsTool(self.db))
        self.register(GetAdminOrdersTool(self.db))
        self.register(GetCDNStorageStatsTool(self.db))

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_tools_for_role(self, role: str) -> List[BaseTool]:
        return [t for t in self._tools.values() if t.is_authorized(role)]

    def get_schemas_for_role(self, role: str) -> List[Dict[str, Any]]:
        return [t.to_openai_schema() for t in self.get_tools_for_role(role)]
