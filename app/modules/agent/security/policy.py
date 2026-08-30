from typing import Tuple, Optional
from pydantic import BaseModel
from app.common.enums import UserRole
from app.modules.agent.schemas.chat import SessionType
from app.modules.agent.schemas.capabilities import ToolCapability, is_role_permitted_for_capability
from app.core.logging import logger

class CallerContext(BaseModel):
    caller_id: str
    caller_role: str
    session_id: str
    session_type: SessionType
    is_authenticated: bool = True

class ToolPolicyGuard:
    """
    Execution-time authorization boundary for all tool calls.
    Never relies solely on the LLM prompt or tool schema exposure.
    Guarantees that malicious or hallucinated tool invocations are blocked.
    """

    @staticmethod
    def authorize_execution(
        tool_name: str,
        capability: ToolCapability,
        roles_allowed: list,
        is_mutation: bool,
        is_destructive: bool,
        context: CallerContext,
    ) -> Tuple[bool, Optional[str]]:
        role = context.caller_role
        actor_id = context.caller_id

        # 1. Unauthenticated Block for Protected Operations
        if not context.is_authenticated or actor_id in ["guest_user", "anonymous", ""]:
            # Only public read tools allowed for unauthenticated visitors
            if is_mutation or is_destructive or capability not in [ToolCapability.READ_CATALOG, ToolCapability.MEDICAL_TRIAGE]:
                logger.warning(f"Security Gate: Blocked unauthenticated attempt to call '{tool_name}'")
                return False, f"Authentication required to execute tool '{tool_name}'."

        # 2. Caller Role Allowlist Check
        if role not in roles_allowed:
            logger.warning(f"Security Gate: Blocked role '{role}' from executing '{tool_name}' (Allowed: {roles_allowed})")
            return False, f"Permission Denied: Role '{role}' is not authorized to execute tool '{tool_name}'."

        # 3. Capability Matrix Enforcement
        if not is_role_permitted_for_capability(role, capability):
            logger.warning(f"Security Gate: Role '{role}' lacks capability '{capability}' for tool '{tool_name}'")
            return False, f"Permission Denied: Missing required capability '{capability}' for tool '{tool_name}'."

        # 4. Session Type Mismatch Check
        if (is_mutation or is_destructive) and context.session_type != SessionType.ADMIN:
            if role not in [UserRole.ADMIN.value, UserRole.DEVELOPER.value]:
                logger.warning(f"Security Gate: Non-admin session attempted administrative mutation '{tool_name}'")
                return False, f"Permission Denied: Administrative tools cannot be executed in standard user sessions."

        # 5. Destructive Operations Require Administrative Roles
        if is_destructive:
            if role not in [UserRole.ADMIN.value, UserRole.DEVELOPER.value]:
                logger.warning(f"Security Gate: Role '{role}' attempted destructive tool '{tool_name}'")
                return False, f"Permission Denied: Destructive operations strictly require ADMIN role."

        return True, None
