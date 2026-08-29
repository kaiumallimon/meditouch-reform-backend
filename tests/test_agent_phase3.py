import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.schemas.chat import SessionType, StreamEventType
from app.modules.agent.memory.repository import AgentMemoryRepository
from app.modules.agent.memory.session import SessionMemoryManager
from app.modules.agent.orchestrator import AgentOrchestrator
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.security.audit import AgentAuditService
from app.common.enums import UserRole

@pytest.mark.asyncio
async def test_session_memory_repository_lifecycle():
    mock_db = MagicMock()
    mock_db.chat_sessions.insert_one = AsyncMock()
    mock_db.chat_sessions.find_one = AsyncMock(return_value={
        "id": "ses_99",
        "user_id": "usr_1",
        "session_type": "USER",
        "title": "Test Chat",
        "is_archived": False,
    })
    mock_db.chat_sessions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_db.chat_messages.insert_one = AsyncMock()
    
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"id": "msg_1", "role": "user", "content": "Hello", "session_id": "ses_99"},
        {"id": "msg_2", "role": "assistant", "content": "Hi there", "session_id": "ses_99"},
    ])
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_db.chat_messages.find = MagicMock(return_value=mock_cursor)

    repo = AgentMemoryRepository(mock_db)
    memory_mgr = SessionMemoryManager(repo)

    # 1. Create Session
    session = await repo.create_session("usr_1", SessionType.USER, "Test Chat")
    assert session["user_id"] == "usr_1"
    assert session["session_type"] == "USER"

    # 2. Add Message
    msg = await repo.add_message("ses_99", "usr_1", "user", "What is Napa?")
    assert msg["role"] == "user"
    assert msg["content"] == "What is Napa?"

    # 3. Context formatting for LLM
    context = await memory_mgr.get_recent_messages_for_llm("ses_99", window_size=10)
    assert len(context) == 2
    assert context[0]["role"] == "user"
    assert context[1]["role"] == "assistant"

@pytest.mark.asyncio
async def test_orchestrator_multi_turn_tool_execution():
    mock_db = MagicMock()
    mock_db.agent_audit_logs.insert_one = AsyncMock()

    # Mock medicines search collection query
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {
            "id": "med_1",
            "slug": "napa-extra",
            "brand": "Napa Extra",
            "generic_name": "Paracetamol + Caffeine",
            "strength": "500 mg + 65 mg",
            "dosage_form": "Tablet",
            "unit_price": 3.00,
            "pack_size": "10 Tablets/Strip",
            "in_stock": True,
            "stock_count": 500,
            "requires_prescription": False,
            "medicine_image": "https://cdn.example.com/napa.jpg",
            "manufacturer": "Beximco",
        }
    ])
    mock_cursor.skip = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_db.medicines.find = MagicMock(return_value=mock_cursor)
    mock_db.medicines.count_documents = AsyncMock(return_value=1)

    registry = ToolRegistry(mock_db)
    audit = AgentAuditService(mock_db)

    # Mock LLM: Turn 1 calls `search_medicines`, Turn 2 outputs final answer
    mock_llm = MagicMock()
    mock_llm.chat_complete = AsyncMock(side_effect=[
        # Turn 1 Response: Model calls tool
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "search_medicines",
                                    "arguments": '{"query": "Napa"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        # Turn 2 Response: Model produces final text answer
        {
            "choices": [
                {
                    "message": {
                        "content": "Napa Extra is available in stock for ৳ 3.00 per unit.",
                        "tool_calls": None,
                    }
                }
            ]
        },
    ])

    orchestrator = AgentOrchestrator(
        llm=mock_llm,
        registry=registry,
        audit_service=audit,
    )

    events = []
    async for ev in orchestrator.execute_turn_stream(
        session_id="ses_test_turn",
        user_id="usr_1",
        user_role=UserRole.USER.value,
        session_type=SessionType.USER,
        user_message="Check Napa Extra price",
        conversation_history=[],
    ):
        events.append(ev)

    event_types = [e["event"] for e in events]

    assert StreamEventType.STATE.value in event_types
    assert StreamEventType.TOOL_CALL.value in event_types
    assert StreamEventType.TOOL_RESULT.value in event_types
    assert StreamEventType.MEDICINE_CARDS.value in event_types
    assert StreamEventType.TOKEN.value in event_types
    assert StreamEventType.DONE.value in event_types

    # Verify tool execution event details
    tool_call_event = next(e for e in events if e["event"] == StreamEventType.TOOL_CALL.value)
    assert tool_call_event["data"]["tool"] == "search_medicines"
    assert tool_call_event["data"]["arguments"]["query"] == "Napa"
