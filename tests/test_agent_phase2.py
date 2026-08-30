import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.schemas.tools import ToolExecutionStatus
from app.modules.agent.commands.user_commands import CreateUserCommand
from app.modules.agent.security.confirmation import confirmation_manager
from app.modules.agent.tools.admin.users import CreateUserTool, DeactivateUserTool
from app.common.enums import UserRole

def test_tool_registry_rbac_matrix():
    mock_db = MagicMock()
    registry = ToolRegistry(mock_db)

    # 1. User Role can only see read tools
    user_tools = registry.get_tools_for_role(UserRole.USER.value)
    user_tool_names = {t.name for t in user_tools}
    
    assert "search_medicines" in user_tool_names
    assert "get_medicine_details" in user_tool_names
    assert "suggest_medicines_for_symptoms" in user_tool_names
    assert "search_doctors" in user_tool_names
    assert "get_my_profile" in user_tool_names
    assert "get_my_orders" in user_tool_names
    assert "get_my_appointments" in user_tool_names
    
    # User must NEVER see admin tools
    assert "create_user" not in user_tool_names
    assert "deactivate_user" not in user_tool_names
    assert "delete_user" not in user_tool_names
    assert "create_doctor" not in user_tool_names
    assert "verify_doctor" not in user_tool_names
    assert "create_medicine" not in user_tool_names
    assert "delete_medicine" not in user_tool_names
    assert "get_cdn_storage_stats" not in user_tool_names

    # 2. Admin Role sees all tools
    admin_tools = registry.get_tools_for_role(UserRole.ADMIN.value)
    admin_tool_names = {t.name for t in admin_tools}

    assert "search_medicines" in admin_tool_names
    assert "search_users" in admin_tool_names
    assert "create_user" in admin_tool_names
    assert "deactivate_user" in admin_tool_names
    assert "delete_user" in admin_tool_names
    assert "create_doctor" in admin_tool_names
    assert "verify_doctor" in admin_tool_names
    assert "delete_doctor" in admin_tool_names
    assert "create_medicine" in admin_tool_names
    assert "update_medicine_stock" in admin_tool_names
    assert "delete_medicine" in admin_tool_names
    assert "get_platform_summary_stats" in admin_tool_names
    assert "query_audit_logs" in admin_tool_names
    assert "get_all_orders_admin" in admin_tool_names
    assert "get_cdn_storage_stats" in admin_tool_names

@pytest.mark.asyncio
async def test_search_users_tool():
    mock_db = MagicMock()
    mock_db.users.find_one = AsyncMock(return_value={
        "id": "usr_kali_123",
        "name": "Kaium Limon",
        "phone": "+8801711223344",
        "email": "kalimon291@gmail.com",
        "role": "ADMIN",
        "is_active": True,
        "gender": "male",
        "created_at": "2026-08-30",
    })

    from app.modules.agent.tools.admin.users import SearchUsersTool
    tool = SearchUsersTool(mock_db)

    # Search by email
    res = await tool.execute(
        arguments={"query": "kalimon291@gmail.com"},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_search",
    )

    assert res.status == ToolExecutionStatus.SUCCESS
    assert res.result["total"] == 1
    assert res.result["users"][0]["email"] == "kalimon291@gmail.com"
    assert res.result["users"][0]["name"] == "Kaium Limon"

def test_pydantic_command_object_validation():
    # Valid command
    cmd = CreateUserCommand(
        name="John Doe",
        phone="+8801711223344",
        email="john@example.com",
        role=UserRole.USER,
    )
    assert cmd.name == "John Doe"
    assert cmd.phone == "+8801711223344"
    assert cmd.role == UserRole.USER

    # Rejection of invalid phone or missing name
    with pytest.raises(Exception):
        CreateUserCommand(name="J", phone="123") # name too short, phone too short

@pytest.mark.asyncio
async def test_tool_gateway_blocks_unauthorized_execution():
    mock_db = MagicMock()
    tool = CreateUserTool(mock_db)

    # Non-admin execution attempt
    res = await tool.execute(
        arguments={"name": "Hacker", "phone": "+8801711223344"},
        caller_id="usr_normal_1",
        caller_role=UserRole.USER.value,
        session_id="ses_1",
    )

    assert res.status == ToolExecutionStatus.PERMISSION_DENIED
    assert "Admin privileges required" in res.error_message

@pytest.mark.asyncio
async def test_deactivate_user_requires_two_step_confirmation():
    mock_db = MagicMock()
    # Mock finding user in resolver
    mock_db.users.find_one = AsyncMock(return_value={
        "id": "usr_victim_99",
        "name": "Target User",
        "phone": "+8801999888777",
        "role": "USER",
        "is_active": True,
    })

    tool = DeactivateUserTool(mock_db)

    # Step 1: Initial invocation without confirmation token -> returns CONFIRMATION_REQUIRED
    res1 = await tool.execute(
        arguments={"query": "+8801999888777"},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_deactivate",
    )

    assert res1.status == ToolExecutionStatus.CONFIRMATION_REQUIRED
    assert res1.requires_confirmation is True
    assert res1.confirmation_token is not None

    token = res1.confirmation_token

    # Mock admin update service
    mock_db.users.find_one = AsyncMock(return_value={
        "id": "usr_victim_99",
        "name": "Target User",
        "phone": "+8801999888777",
        "role": "USER",
        "is_active": True
    })
    mock_db.users.find_one_and_update = AsyncMock(return_value={
        "id": "usr_victim_99",
        "name": "Target User",
        "phone": "+8801999888777",
        "role": "USER",
        "is_active": False
    })
    mock_db.audit_logs.insert_one = AsyncMock()

    # Step 2: Second invocation WITH confirmation token -> performs execution
    res2 = await tool.execute(
        arguments={},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_deactivate",
        confirmation_token=token,
    )

    assert res2.status == ToolExecutionStatus.SUCCESS
    assert res2.result["status"] == "DEACTIVATED"

@pytest.mark.asyncio
async def test_create_user_requires_two_step_confirmation():
    mock_db = MagicMock()
    tool = CreateUserTool(mock_db)

    # Step 1: Initial call without confirmation token -> returns CONFIRMATION_REQUIRED
    res1 = await tool.execute(
        arguments={"name": "New Candidate", "phone": "+8801711223344", "email": "candidate@example.com", "role": "USER"},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_create_user",
    )

    assert res1.status == ToolExecutionStatus.CONFIRMATION_REQUIRED
    assert res1.requires_confirmation is True
    assert res1.confirmation_token is not None
    assert "candidate@example.com" in res1.confirmation_prompt
