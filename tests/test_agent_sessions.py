"""
Automated unit & integration test suite for AI Assistant Conversation/Session System.

Validates the architectural invariants:
1. Lazy session creation: No session in database on empty drafts; created only on first user message.
2. Dynamic titles: Initial title is derived from the first user message.
3. Zero-message filtering: `list_user_sessions` returns only sessions with `message_count > 0`.
4. Subsequent messages: Multi-turn chat reuses existing `session_id`.
5. Legacy data cleanup: Safely archives 0-message sessions and repairs titles for sessions with messages.
6. Session deletion: Archiving removes session from user history without creating replacement sessions.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.memory.repository import AgentMemoryRepository
from app.modules.agent.memory.session import SessionMemoryManager
from app.modules.agent.service import AgentChatService
from app.modules.agent.schemas.chat import SessionType, ChatRequest


# ─────────────────────────────────────────────────────────────────────────────
# 1. UNIT TESTS: SessionMemoryManager & Title Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_initial_title_from_medicine_price_query():
    repo = MagicMock()
    mgr = SessionMemoryManager(repo)
    title = mgr.generate_initial_title("What is the price of Tufnil 1 strip?")
    assert "Tufnil" in title
    assert len(title) <= 36


def test_generate_initial_title_from_symptom_query():
    repo = MagicMock()
    mgr = SessionMemoryManager(repo)
    title = mgr.generate_initial_title("I am having a severe cough and fever for 3 days")
    assert "cough" in title.lower()
    assert len(title) <= 36


def test_generate_initial_title_cleans_markdown_and_newlines():
    repo = MagicMock()
    mgr = SessionMemoryManager(repo)
    title = mgr.generate_initial_title("### **Search Napa Extra**\nand check availability")
    assert not title.startswith("#")
    assert not title.startswith("*")
    assert "\n" not in title


def test_generate_initial_title_empty_fallback():
    repo = MagicMock()
    mgr = SessionMemoryManager(repo)
    assert mgr.generate_initial_title("") == "Conversation"
    assert mgr.generate_initial_title("   ") == "Conversation"


# ─────────────────────────────────────────────────────────────────────────────
# 2. UNIT & REPOSITORY TESTS: AgentMemoryRepository
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_session_sets_initial_message_count():
    mock_db = MagicMock()
    mock_db.chat_sessions.insert_one = AsyncMock()
    repo = AgentMemoryRepository(mock_db)

    doc = await repo.create_session(user_id="u1", session_type=SessionType.USER, title="Test Session")
    assert doc["message_count"] == 0
    assert doc["title"] == "Test Session"
    assert doc["is_archived"] is False
    assert "id" in doc
    assert "last_message_at" in doc
    mock_db.chat_sessions.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_add_message_atomically_increments_message_count():
    mock_db = MagicMock()
    mock_db.chat_messages.insert_one = AsyncMock()
    mock_db.chat_sessions.update_one = AsyncMock()
    repo = AgentMemoryRepository(mock_db)

    msg = await repo.add_message(
        session_id="ses_1",
        user_id="u1",
        role="user",
        content="What is Napa?",
    )

    assert msg["content"] == "What is Napa?"
    mock_db.chat_messages.insert_one.assert_called_once()
    mock_db.chat_sessions.update_one.assert_called_once()

    # Check update_one arguments for message_count increment
    call_args = mock_db.chat_sessions.update_one.call_args[0]
    filter_dict = call_args[0]
    update_dict = call_args[1]
    assert filter_dict == {"id": "ses_1"}
    assert "$inc" in update_dict
    assert update_dict["$inc"]["message_count"] == 1
    assert "$set" in update_dict
    assert "last_message_at" in update_dict["$set"]


@pytest.mark.asyncio
async def test_list_user_sessions_filters_out_zero_message_sessions():
    """Validates that list_user_sessions query excludes empty sessions (message_count > 0)."""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[
        {"id": "s1", "title": "Tufnil price", "message_count": 2, "user_id": "u1"},
    ])
    mock_db.chat_sessions.find.return_value = mock_cursor

    repo = AgentMemoryRepository(mock_db)
    results = await repo.list_user_sessions(user_id="u1")

    assert len(results) == 1
    assert results[0]["title"] == "Tufnil price"

    # Verify query filter contains message_count > 0
    query_passed = mock_db.chat_sessions.find.call_args[0][0]
    assert query_passed["user_id"] == "u1"
    assert query_passed["message_count"] == {"$gt": 0}
    assert query_passed["is_archived"] == {"$ne": True}


@pytest.mark.asyncio
async def test_cleanup_legacy_empty_sessions():
    """
    Validates that cleanup_legacy_empty_sessions:
    1. Archives empty 0-message sessions.
    2. Repairs placeholder titles for sessions that contain real messages.
    """
    mock_db = MagicMock()

    # Mock finding 2 sessions: s_empty (0 msgs) and s_has_msgs (2 msgs with title 'New Conversation')
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"id": "s_empty", "title": "New Conversation", "is_archived": False},
        {"id": "s_has_msgs", "title": "New Conversation", "is_archived": False},
    ])
    mock_db.chat_sessions.find.return_value = mock_cursor

    # count_documents: 0 for s_empty, 2 for s_has_msgs
    async def count_docs(q):
        if q.get("session_id") == "s_empty":
            return 0
        return 2

    mock_db.chat_messages.count_documents = AsyncMock(side_effect=count_docs)

    # find_one first user message for s_has_msgs
    mock_db.chat_messages.find_one = AsyncMock(return_value={
        "session_id": "s_has_msgs",
        "role": "user",
        "content": "Check price for Tufnil 200mg",
    })
    mock_db.chat_sessions.update_one = AsyncMock()

    repo = AgentMemoryRepository(mock_db)
    stats = await repo.cleanup_legacy_empty_sessions()

    assert stats["archived_empty_sessions"] == 1
    assert stats["repaired_titles"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. SERVICE TESTS: Lazy Session Creation & Multi-Turn Continuation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_get_or_create_session_lazy_creates_on_first_message():
    """When session_id is None, creates a session with title derived from first message."""
    mock_db = MagicMock()
    mock_db.chat_sessions.insert_one = AsyncMock()
    service = AgentChatService(mock_db)

    session = await service.get_or_create_session(
        session_id=None,
        user_id="u1",
        user_role="USER",
        first_message="What is the price of Tufnil?",
    )

    assert session is not None
    assert "Tufnil" in session["title"]
    assert session["user_id"] == "u1"


@pytest.mark.asyncio
async def test_service_get_or_create_session_reuses_existing_session():
    """When session_id exists, reuses it without creating a new session document."""
    mock_db = MagicMock()
    existing_session = {
        "id": "ses_existing_999",
        "user_id": "u1",
        "session_type": "USER",
        "title": "Existing Chat",
        "message_count": 4,
    }
    mock_db.chat_sessions.find_one = AsyncMock(return_value=existing_session)
    mock_db.chat_sessions.insert_one = AsyncMock()

    service = AgentChatService(mock_db)
    session = await service.get_or_create_session(
        session_id="ses_existing_999",
        user_id="u1",
        user_role="USER",
        first_message="Follow up message",
    )

    assert session["id"] == "ses_existing_999"
    assert session["title"] == "Existing Chat"
    # insert_one should NOT have been called
    mock_db.chat_sessions.insert_one.assert_not_called()

