"""
Automated unit & integration test suite for ResponseAssembler & Streaming UI Ordering.

Validates the architectural invariants:
1. TOOL RESULT != USER-FACING RESPONSE (Tools produce data; ResponseAssembler produces structured UI).
2. TEXT STREAMING happens in real-time; STRUCTURED UI is emitted only on response finalization.
3. Stable response_id is attached to all SSE events in a turn.
4. Clarification events clear buffered UI without emitting orphaned cards.
5. Multiple tool calls do not emit intermediate cards.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.assembler import ResponseAssembler
from app.modules.agent.orchestrator import AgentOrchestrator
from app.modules.agent.schemas.chat import SessionType, StreamEventType, AgentState
from app.modules.agent.schemas.tools import ToolResult, ToolExecutionStatus
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.security.audit import AgentAuditService


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: ResponseAssembler
# ─────────────────────────────────────────────────────────────────────────────

def test_response_assembler_buffers_search_medicines_results():
    """Validates that search_medicines tool results are buffered and deduplicated."""
    assembler = ResponseAssembler(response_id="resp_test1")

    # Record search results
    assembler.record_tool_result(
        tool_name="search_medicines",
        arguments={"query": "Tufnil"},
        result={
            "count": 1,
            "medicines": [
                {
                    "id": "med_101",
                    "slug": "tufnil-200-mg-tablet",
                    "brand": "Tufnil",
                    "generic_name": "Tolfenamic acid",
                    "strength": "200 mg",
                    "dosage_form": "Tablet",
                    "unit_price": 100.0,
                    "pack_size": "10 tablets",
                    "in_stock": True,
                    "stock_count": 100,
                }
            ],
        },
    )

    cards = assembler.get_medicine_cards()
    assert len(cards) == 1
    assert cards[0]["brand"] == "Tufnil"
    assert cards[0]["slug"] == "tufnil-200-mg-tablet"

    # Recording duplicate medicine ID should not duplicate card
    assembler.record_tool_result(
        tool_name="search_medicines",
        arguments={"query": "Tufnil"},
        result={
            "count": 1,
            "medicines": [
                {
                    "id": "med_101",
                    "slug": "tufnil-200-mg-tablet",
                    "brand": "Tufnil",
                }
            ],
        },
    )
    assert len(assembler.get_medicine_cards()) == 1


def test_response_assembler_buffers_get_medicine_details():
    """Validates that get_medicine_details tool results are properly normalized into medicine cards."""
    assembler = ResponseAssembler(response_id="resp_test2")

    assembler.record_tool_result(
        tool_name="get_medicine_details",
        arguments={"slug_or_id": "napa-extra"},
        result={
            "id": "med_202",
            "slug": "napa-extra-tablet",
            "brand": "Napa Extra",
            "generic_name": "Paracetamol + Caffeine",
            "strength": "500 mg + 65 mg",
            "dosage_form": "Tablet",
            "unit_price": 2.50,
            "pack_size": "100 tablets",
            "in_stock": True,
            "stock_count": 500,
            "requires_prescription": False,
        },
    )

    cards = assembler.get_medicine_cards()
    assert len(cards) == 1
    assert cards[0]["brand"] == "Napa Extra"
    assert cards[0]["generic_name"] == "Paracetamol + Caffeine"


def test_response_assembler_clear_discards_buffered_components():
    """Validates that calling clear() removes all buffered components."""
    assembler = ResponseAssembler(response_id="resp_test3")
    assembler.record_tool_result(
        tool_name="search_medicines",
        arguments={"query": "Napa"},
        result={"medicines": [{"id": "m1", "brand": "Napa"}]},
    )
    assert len(assembler.get_medicine_cards()) == 1

    assembler.clear()
    assert len(assembler.get_medicine_cards()) == 0
    assert len(assembler.assemble_final_components()) == 0


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS: Orchestrator ReAct Streaming & UI Ordering
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medicine_card_not_emitted_during_tool_execution_but_on_completion():
    """
    TEST 8 & TEST 9: When search_medicines is called, no medicine_cards event is emitted
    during the tool execution phase. It must appear strictly after text streaming / on finalization.
    """
    mock_llm = MagicMock()
    mock_llm.model_tag = "test-model"

    # Step 1: LLM decides to call search_medicines
    step1_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "search_medicines",
                                "arguments": '{"query": "Tufnil"}',
                            },
                        }
                    ],
                }
            }
        ]
    }

    # Step 2: LLM generates final answer text after observing tool result
    step2_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Tufnil 200 mg Tablet — 1 strip (10 tablets): ৳100.00",
                    "tool_calls": None,
                }
            }
        ]
    }

    mock_llm.chat_complete = AsyncMock(side_effect=[step1_response, step2_response])

    # Setup mock tool that returns catalog results
    mock_tool = MagicMock()
    mock_tool.name = "search_medicines"
    mock_tool.execute = AsyncMock(
        return_value=ToolResult(
            tool_call_id="call_1",
            name="search_medicines",
            status=ToolExecutionStatus.SUCCESS,
            result={
                "count": 1,
                "medicines": [
                    {
                        "id": "med_101",
                        "slug": "tufnil-200-mg-tablet",
                        "brand": "Tufnil",
                        "generic_name": "Tolfenamic acid",
                        "unit_price": 100.0,
                    }
                ],
            },
        )
    )

    registry = ToolRegistry(MagicMock())
    registry.get_tool = MagicMock(return_value=mock_tool)
    registry.authorize_execution = MagicMock(return_value=(True, None))
    registry.get_schemas_for_context = MagicMock(return_value=[])

    audit = AgentAuditService(MagicMock())
    orchestrator = AgentOrchestrator(llm=mock_llm, registry=registry, audit_service=audit)

    events = []
    async for event in orchestrator.execute_turn_stream(
        session_id="ses_test",
        user_id="user_test",
        user_role="USER",
        session_type=SessionType.USER,
        user_message="What is the price of Tufnil 1 strip?",
        conversation_history=[],
    ):
        events.append(event)

    event_types = [e["event"] for e in events]

    # Verify event ordering:
    # 1. TOOL_CALL happens
    assert StreamEventType.TOOL_CALL.value in event_types
    tool_call_idx = event_types.index(StreamEventType.TOOL_CALL.value)

    # 2. TOOL_RESULT happens
    assert StreamEventType.TOOL_RESULT.value in event_types
    tool_result_idx = event_types.index(StreamEventType.TOOL_RESULT.value)

    # 3. Text TOKEN happens AFTER tool_result
    assert StreamEventType.TOKEN.value in event_types
    token_idx = event_types.index(StreamEventType.TOKEN.value)
    assert token_idx > tool_result_idx

    # 4. MEDICINE_CARDS event MUST occur AFTER text tokens (at finalization stage)
    assert StreamEventType.MEDICINE_CARDS.value in event_types
    medicine_cards_idx = event_types.index(StreamEventType.MEDICINE_CARDS.value)
    assert medicine_cards_idx > token_idx

    # 5. DONE event includes response_id and medicine_cards
    done_event = next(e for e in events if e["event"] == StreamEventType.DONE.value)
    assert done_event["data"]["finish_reason"] == "stop"
    assert "Tufnil" in done_event["data"]["full_content"]
    assert len(done_event["data"]["medicine_cards"]) == 1
    assert done_event["data"]["medicine_cards"][0]["brand"] == "Tufnil"


@pytest.mark.asyncio
async def test_stable_response_id_present_across_all_stream_events():
    """Validates that a stable response_id is included in all SSE events."""
    mock_llm = MagicMock()
    mock_llm.model_tag = "test-model"
    mock_llm.chat_complete = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Here is information on Napa.",
                    }
                }
            ]
        }
    )

    registry = ToolRegistry(MagicMock())
    registry.get_schemas_for_context = MagicMock(return_value=[])
    audit = AgentAuditService(MagicMock())
    orchestrator = AgentOrchestrator(llm=mock_llm, registry=registry, audit_service=audit)

    events = []
    async for event in orchestrator.execute_turn_stream(
        session_id="ses_test",
        user_id="user_test",
        user_role="USER",
        session_type=SessionType.USER,
        user_message="Hello",
        conversation_history=[],
        response_id="resp_stable_123",
    ):
        events.append(event)

    for ev in events:
        if "data" in ev and isinstance(ev["data"], dict):
            assert ev["data"].get("response_id") == "resp_stable_123"


@pytest.mark.asyncio
async def test_clarification_event_clears_buffered_ui_without_emission():
    """
    TEST 6: When clarification_required is returned by a tool,
    any buffered UI components are discarded immediately and no medicine_cards are emitted.
    """
    mock_llm = MagicMock()
    mock_llm.model_tag = "test-model"

    mock_llm.chat_complete = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_clarif",
                                "function": {
                                    "name": "assess_symptom_safety",
                                    "arguments": '{"symptoms_description": "I have cough"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )

    # Tool returns CLARIFICATION_REQUIRED
    mock_tool = MagicMock()
    mock_tool.name = "assess_symptom_safety"
    mock_tool.execute = AsyncMock(
        return_value=ToolResult(
            tool_call_id="call_clarif",
            name="assess_symptom_safety",
            status=ToolExecutionStatus.CLARIFICATION_REQUIRED,
            result={"status": "CLARIFICATION_REQUIRED", "clarification_id": "clarif_001"},
            requires_clarification=True,
            clarification_id="clarif_001",
            clarification_payload={
                "clarification_id": "clarif_001",
                "message": "Please describe your cough.",
                "questions": [{"id": "duration", "type": "single_select", "question": "Duration?"}],
                "submission": {"action": "submit_clarification", "session_id": "s1", "clarification_id": "clarif_001"},
            },
        )

    )

    registry = ToolRegistry(MagicMock())
    registry.get_tool = MagicMock(return_value=mock_tool)
    registry.authorize_execution = MagicMock(return_value=(True, None))
    registry.get_schemas_for_context = MagicMock(return_value=[])

    audit = AgentAuditService(MagicMock())
    orchestrator = AgentOrchestrator(llm=mock_llm, registry=registry, audit_service=audit)

    events = []
    async for event in orchestrator.execute_turn_stream(
        session_id="s1",
        user_id="u1",
        user_role="USER",
        session_type=SessionType.USER,
        user_message="I have cough",
        conversation_history=[],
    ):
        events.append(event)

    event_types = [e["event"] for e in events]
    assert StreamEventType.CLARIFICATION_REQUIRED.value in event_types
    # medicine_cards MUST NOT be emitted
    assert StreamEventType.MEDICINE_CARDS.value not in event_types
    # Turn terminates immediately with clarification_required
    done_ev = next(e for e in events if e["event"] == StreamEventType.DONE.value)
    assert done_ev["data"]["finish_reason"] == "clarification_required"


@pytest.mark.asyncio
async def test_multiple_tool_calls_no_intermediate_medicine_cards():
    """
    TEST 11: search_medicines -> get_medicine_details -> final response
    No intermediate medicine card event is emitted during the tool loop.
    All cards are delivered once at response finalization.
    """
    mock_llm = MagicMock()
    mock_llm.model_tag = "test-model"

    # Step 1: search_medicines
    step1 = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "search_medicines", "arguments": '{"query": "Tufnil"}'},
                        }
                    ],
                }
            }
        ]
    }

    # Step 2: get_medicine_details
    step2 = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c2",
                            "function": {"name": "get_medicine_details", "arguments": '{"slug_or_id": "tufnil-200-mg"}'},
                        }
                    ],
                }
            }
        ]
    }

    # Step 3: Final answer
    step3 = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Tufnil is an anti-inflammatory tablet containing Tolfenamic acid 200 mg.",
                    "tool_calls": None,
                }
            }
        ]
    }

    mock_llm.chat_complete = AsyncMock(side_effect=[step1, step2, step3])

    def get_mock_tool(name):
        t = MagicMock()
        t.name = name
        if name == "search_medicines":
            t.execute = AsyncMock(
                return_value=ToolResult(
                    tool_call_id="c1",
                    name="search_medicines",
                    status=ToolExecutionStatus.SUCCESS,
                    result={"medicines": [{"id": "m1", "brand": "Tufnil", "slug": "tufnil-200-mg"}]},
                )
            )
        else:
            t.execute = AsyncMock(
                return_value=ToolResult(
                    tool_call_id="c2",
                    name="get_medicine_details",
                    status=ToolExecutionStatus.SUCCESS,
                    result={"id": "m1", "brand": "Tufnil", "slug": "tufnil-200-mg", "dosage_form": "Tablet"},
                )
            )
        return t

    registry = ToolRegistry(MagicMock())
    registry.get_tool = MagicMock(side_effect=get_mock_tool)
    registry.authorize_execution = MagicMock(return_value=(True, None))
    registry.get_schemas_for_context = MagicMock(return_value=[])

    audit = AgentAuditService(MagicMock())
    orchestrator = AgentOrchestrator(llm=mock_llm, registry=registry, audit_service=audit)

    events = []
    async for event in orchestrator.execute_turn_stream(
        session_id="s1",
        user_id="u1",
        user_role="USER",
        session_type=SessionType.USER,
        user_message="Tell me about Tufnil",
        conversation_history=[],
    ):
        events.append(event)

    # Count how many times MEDICINE_CARDS was emitted
    med_card_events = [e for e in events if e["event"] == StreamEventType.MEDICINE_CARDS.value]
    # Exactly ONE final medicine_cards event, after all tools have executed
    assert len(med_card_events) == 1
