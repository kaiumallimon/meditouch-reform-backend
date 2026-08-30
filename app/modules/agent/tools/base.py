from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from app.common.enums import UserRole
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability

class BaseTool(ABC):
    """
    Abstract base class for all agent tools.
    Enforces explicit metadata, capabilities, permissions, and execution boundaries.
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    capability: ToolCapability = ToolCapability.READ_CATALOG
    roles_allowed: List[str] = [
        UserRole.USER.value,
        UserRole.DOCTOR.value,
        UserRole.NURSE.value,
        UserRole.ADMIN.value,
        UserRole.DEVELOPER.value,
    ]
    is_mutation: bool = False
    is_destructive: bool = False
    requires_confirmation: bool = False

    def is_authorized(self, caller_role: str) -> bool:
        return caller_role in self.roles_allowed

    @abstractmethod
    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        """Executes the tool logic against the domain service layer."""
        pass

    def to_openai_schema(self) -> Dict[str, Any]:
        """Converts tool definition to OpenAI-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
