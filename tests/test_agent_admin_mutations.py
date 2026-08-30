import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.tools.admin.medicines import CreateMedicineTool, DeleteMedicineTool
from app.modules.agent.tools.admin.users import CreateUserTool
from app.modules.agent.schemas.tools import ToolExecutionStatus
from app.common.enums import UserRole

@pytest.mark.asyncio
async def test_admin_create_medicine_flow():
    mock_db = MagicMock()
    mock_db.agent_pending_actions.insert_one = AsyncMock()

    tool = CreateMedicineTool(mock_db)

    # Step 1: Initial proposal returns CONFIRMATION_REQUIRED with pending action token
    res1 = await tool.execute(
        arguments={
            "brand": "NewPainRelief 500mg",
            "generic_name": "Paracetamol",
            "unit_price": 2.50,
            "strength": "500mg",
            "dosage_form": "Tablet",
            "stock_count": 50,
        },
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_med",
    )

    assert res1.status == ToolExecutionStatus.CONFIRMATION_REQUIRED
    assert res1.requires_confirmation is True
    assert res1.confirmation_token is not None

    token = res1.confirmation_token

    # Step 2: Confirmation execution delegates to PharmacyService
    mock_db.agent_pending_actions.find_one_and_update = AsyncMock(return_value={
        "id": token,
        "actor_id": "usr_admin_1",
        "session_id": "ses_admin_med",
        "action": "create_medicine",
        "command_data": {
            "brand": "NewPainRelief 500mg",
            "generic_name": "Paracetamol",
            "unit_price": 2.50,
            "strength": "500mg",
            "dosage_form": "Tablet",
            "stock_count": 50,
        },
    })
    mock_db.agent_pending_actions.update_one = AsyncMock()
    mock_db.medicines.find_one = AsyncMock(return_value=None)
    mock_db.medicines.insert_one = AsyncMock(return_value=MagicMock(inserted_id="med_new_99"))
    mock_db.audit_logs.insert_one = AsyncMock()

    res2 = await tool.execute(
        arguments={},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_med",
        confirmation_token=token,
    )

    assert res2.status == ToolExecutionStatus.SUCCESS
    assert res2.result["brand"] == "NewPainRelief 500mg"

@pytest.mark.asyncio
async def test_admin_delete_medicine_with_confirmation_and_audit():
    mock_db = MagicMock()
    mock_db.agent_pending_actions.insert_one = AsyncMock()
    mock_db.medicines.find_one = AsyncMock(return_value={
        "id": "med_del_123",
        "slug": "old-medicine",
        "brand": "OldMedicine",
        "generic_name": "OldGeneric",
        "is_active": True,
    })

    tool = DeleteMedicineTool(mock_db)

    # Step 1: Initial call returns CONFIRMATION_REQUIRED
    res1 = await tool.execute(
        arguments={"medicine": "old-medicine"},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_del_med",
    )

    assert res1.status == ToolExecutionStatus.CONFIRMATION_REQUIRED
    token = res1.confirmation_token
    assert token is not None

    # Step 2: Confirm deletion
    mock_db.agent_pending_actions.find_one_and_update = AsyncMock(return_value={
        "id": token,
        "actor_id": "usr_admin_1",
        "session_id": "ses_admin_del_med",
        "action": "delete_medicine",
        "target_id": "med_del_123",
    })
    mock_db.agent_pending_actions.update_one = AsyncMock()
    mock_db.medicines.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    mock_db.audit_logs.insert_one = AsyncMock()

    res2 = await tool.execute(
        arguments={},
        caller_id="usr_admin_1",
        caller_role=UserRole.ADMIN.value,
        session_id="ses_admin_del_med",
        confirmation_token=token,
    )

    assert res2.status == ToolExecutionStatus.SUCCESS
    assert res2.result["status"] == "DELETED"
