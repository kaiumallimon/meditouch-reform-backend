import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.schemas.chat import AgentState, SessionType, StreamEventType
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.state import AgentExecutionState
from app.modules.agent.security.confirmation import ConfirmationManager
from app.modules.agent.security.audit import AgentAuditService
from app.modules.agent.llm.tokenrouter import TokenRouterProvider

def test_agent_execution_state_transitions():
    state = AgentExecutionState(
        session_id="ses_test_1",
        user_id="usr_test_1",
        user_role="USER",
        session_type=SessionType.USER,
    )
    assert state.current_state == AgentState.RECEIVED
    assert state.step_count == 0

    state.transition(AgentState.PLANNING)
    assert state.current_state == AgentState.PLANNING

    state.increment_step()
    assert state.step_count == 1

    state.increment_tool_call()
    assert state.tool_call_count == 1

def test_confirmation_manager_lifecycle():
    cm = ConfirmationManager(ttl_seconds=2)
    
    # 1. Create pending confirmation
    token = cm.create_pending_confirmation(
        session_id="ses_admin_1",
        action="delete_user",
        target_type="USER",
        target_id="usr_target_99",
        target_name="John Doe",
        summary="Deletes user John Doe permanently",
        command_data={"user_id": "usr_target_99"},
    )
    assert token is not None

    # 2. Lookup pending item
    pending = cm.get_pending_by_session("ses_admin_1")
    assert pending is not None
    assert pending["target_id"] == "usr_target_99"

    # 3. Session mismatch rejects
    invalid_consume = cm.validate_and_consume(token, session_id="ses_wrong_session")
    assert invalid_consume is None

    # 4. Valid consume succeeds
    valid_consume = cm.validate_and_consume(token, session_id="ses_admin_1")
    assert valid_consume is not None
    assert valid_consume["action"] == "delete_user"

    # 5. Token is single-use (already consumed)
    second_consume = cm.validate_and_consume(token, session_id="ses_admin_1")
    assert second_consume is None

def test_confirmation_manager_expiration():
    cm = ConfirmationManager(ttl_seconds=0.1)
    token = cm.create_pending_confirmation(
        session_id="ses_exp_1",
        action="deactivate_user",
        target_type="USER",
        target_id="usr_1",
        target_name=None,
        summary="Deactivate",
        command_data={},
    )
    time.sleep(0.2)
    consumed = cm.validate_and_consume(token, session_id="ses_exp_1")
    assert consumed is None

@pytest.mark.asyncio
async def test_agent_audit_service_sanitizes_credentials():
    mock_db = MagicMock()
    mock_db.agent_audit_logs.insert_one = AsyncMock()

    audit_svc = AgentAuditService(mock_db)
    
    metadata = {
        "user_name": "Alice",
        "phone": "+8801711223344",
        "password": "SuperSecretPassword123!",
        "auth_token": "eyJhbGciOi...",
        "nested": {
            "jwt_secret": "my_secret_key",
            "safe_note": "Account created via AI",
        }
    }

    audit_id = await audit_svc.log_action(
        actor_id="usr_admin_1",
        actor_role="ADMIN",
        session_id="ses_1",
        action="CREATE_USER",
        resource_type="USER",
        resource_id="usr_alice_1",
        tool_name="create_user",
        metadata=metadata,
    )

    assert audit_id is not None
    mock_db.agent_audit_logs.insert_one.assert_called_once()
    
    logged_doc = mock_db.agent_audit_logs.insert_one.call_args[0][0]
    logged_meta = logged_doc["metadata"]
    
    assert logged_meta["user_name"] == "Alice"
    assert logged_meta["password"] == "[REDACTED]"
    assert logged_meta["auth_token"] == "[REDACTED]"
    assert logged_meta["nested"]["jwt_secret"] == "[REDACTED]"
    assert logged_meta["nested"]["safe_note"] == "Account created via AI"

def test_tokenrouter_provider_initialization():
    provider = TokenRouterProvider(
        api_key="test_key_123",
        base_url="https://api.tokenrouter.ai/v1",
        model="gpt-4o-mini",
    )
    assert provider.api_key == "test_key_123"
    assert provider.base_url == "https://api.tokenrouter.ai/v1"
    assert provider.model == "gpt-4o-mini"
    assert provider.headers["Authorization"] == "Bearer test_key_123"
