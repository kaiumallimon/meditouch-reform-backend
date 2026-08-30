import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.security.pending_actions import AgentPendingActionRepository

@pytest.mark.asyncio
async def test_pending_action_creation_and_atomic_consumption():
    mock_db = MagicMock()
    mock_db.agent_pending_actions.insert_one = AsyncMock()

    # Mock atomic find_one_and_update
    mock_db.agent_pending_actions.find_one_and_update = AsyncMock(return_value={
        "id": "token_abc_123",
        "actor_id": "adm_1",
        "session_id": "ses_admin_1",
        "action": "delete_medicine",
        "status": "PENDING",
        "command_data": {"medicine_id": "med_1"},
    })

    repo = AgentPendingActionRepository(mock_db)

    # 1. Create action
    token = await repo.create_pending_action(
        actor_id="adm_1",
        actor_role="ADMIN",
        session_id="ses_admin_1",
        action="delete_medicine",
        target_type="MEDICINE",
        target_id="med_1",
        target_name="Napa",
        summary="Delete Napa",
        command_data={"medicine_id": "med_1"},
    )
    assert token is not None
    assert mock_db.agent_pending_actions.insert_one.called

    # 2. Consume with matching actor & session
    consumed = await repo.validate_and_consume(
        token="token_abc_123",
        actor_id="adm_1",
        session_id="ses_admin_1",
    )
    assert consumed is not None
    assert consumed["action"] == "delete_medicine"

@pytest.mark.asyncio
async def test_pending_action_rejects_actor_or_session_mismatch():
    mock_db = MagicMock()
    # If conditions do not match, MongoDB find_one_and_update returns None
    mock_db.agent_pending_actions.find_one_and_update = AsyncMock(return_value=None)

    repo = AgentPendingActionRepository(mock_db)

    # Wrong session attempt
    consumed = await repo.validate_and_consume(
        token="token_abc_123",
        actor_id="adm_1",
        session_id="ses_attacker_session",
    )
    assert consumed is None

    # Wrong actor attempt
    consumed_wrong_actor = await repo.validate_and_consume(
        token="token_abc_123",
        actor_id="adm_attacker",
        session_id="ses_admin_1",
    )
    assert consumed_wrong_actor is None
