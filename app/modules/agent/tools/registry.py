from typing import Dict, List, Optional, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.tools.user.medicines import SearchMedicinesTool, GetMedicineDetailsTool, CheckMedicineStockTool
from app.modules.agent.tools.user.clinical import SuggestMedicinesForSymptomsTool
from app.modules.agent.tools.user.doctors import SearchDoctorsTool, GetDoctorDetailsTool
from app.modules.agent.tools.admin.users import CreateUserTool, DeactivateUserTool, DeleteUserTool
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
        # User / Read Tools
        self.register(SearchMedicinesTool(self.db))
        self.register(GetMedicineDetailsTool(self.db))
        self.register(CheckMedicineStockTool(self.db))
        self.register(SuggestMedicinesForSymptomsTool(self.db))
        self.register(SearchDoctorsTool(self.db))
        self.register(GetDoctorDetailsTool(self.db))

        # Admin / Write Tools
        self.register(CreateUserTool(self.db))
        self.register(DeactivateUserTool(self.db))
        self.register(DeleteUserTool(self.db))
        self.register(GetCDNStorageStatsTool(self.db))

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_tools_for_role(self, role: str) -> List[BaseTool]:
        return [t for t in self._tools.values() if t.is_authorized(role)]

    def get_schemas_for_role(self, role: str) -> List[Dict[str, Any]]:
        return [t.to_openai_schema() for t in self.get_tools_for_role(role)]
