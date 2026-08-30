import pytest
from unittest.mock import MagicMock
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.schemas.chat import SessionType
from app.modules.agent.schemas.capabilities import ToolCapability, is_role_permitted_for_capability
from app.modules.agent.security.policy import ToolPolicyGuard, CallerContext
from app.common.enums import UserRole

def test_capability_matrix_role_mappings():
    # User cannot have mutation capabilities
    assert not is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.CREATE_USER)
    assert not is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.DELETE_PROFILE)
    assert not is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.CREATE_MEDICINE)
    assert not is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.DELETE_MEDICINE)

    # User has safe read and triage capabilities
    assert is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.READ_CATALOG)
    assert is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.MEDICAL_TRIAGE)
    assert is_role_permitted_for_capability(UserRole.USER.value, ToolCapability.READ_PERSONAL_DATA)

    # Admin has full capabilities
    assert is_role_permitted_for_capability(UserRole.ADMIN.value, ToolCapability.CREATE_USER)
    assert is_role_permitted_for_capability(UserRole.ADMIN.value, ToolCapability.DELETE_MEDICINE)

def test_tool_registry_context_filtering():
    mock_db = MagicMock()
    registry = ToolRegistry(mock_db)

    # 1. USER context
    user_tools = registry.get_tools_for_context(UserRole.USER.value, SessionType.USER)
    user_tool_names = {t.name for t in user_tools}

    assert "assess_symptom_safety" in user_tool_names
    assert "search_medicines" in user_tool_names
    assert "get_medicine_details" in user_tool_names
    assert "search_doctors" in user_tool_names

    # Admin tools MUST NOT be in user tools
    assert "create_user" not in user_tool_names
    assert "delete_user" not in user_tool_names
    assert "delete_medicine" not in user_tool_names
    assert "create_doctor" not in user_tool_names

    # 2. ADMIN context in ADMIN session
    admin_tools = registry.get_tools_for_context(UserRole.ADMIN.value, SessionType.ADMIN)
    admin_tool_names = {t.name for t in admin_tools}

    assert "create_user" in admin_tool_names
    assert "delete_medicine" in admin_tool_names
    assert "verify_doctor" in admin_tool_names

def test_execution_time_policy_guard_blocks_unauthorized_invocations():
    # User attempting to call create_user
    ctx_user = CallerContext(
        caller_id="usr_user_123",
        caller_role=UserRole.USER.value,
        session_id="ses_user_1",
        session_type=SessionType.USER,
        is_authenticated=True,
    )
    is_auth, err = ToolPolicyGuard.authorize_execution(
        tool_name="create_user",
        capability=ToolCapability.CREATE_USER,
        roles_allowed=[UserRole.ADMIN.value, UserRole.DEVELOPER.value],
        is_mutation=True,
        is_destructive=False,
        context=ctx_user,
    )
    assert is_auth is False
    assert "Permission Denied" in err

def test_unauthenticated_caller_blocked_from_mutations():
    ctx_anon = CallerContext(
        caller_id="guest_user",
        caller_role=UserRole.USER.value,
        session_id="ses_anon_1",
        session_type=SessionType.USER,
        is_authenticated=False,
    )
    is_auth, err = ToolPolicyGuard.authorize_execution(
        tool_name="create_user",
        capability=ToolCapability.CREATE_USER,
        roles_allowed=[UserRole.ADMIN.value],
        is_mutation=True,
        is_destructive=False,
        context=ctx_anon,
    )
    assert is_auth is False
    assert "Authentication required" in err
