import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.schemas.clarification import (
    ClarificationQuestion,
    ClarificationOption,
    ClarificationSubmissionRequest,
    ClarificationAnswer,
    QuestionType,
)
from app.modules.agent.security.clarifications import AgentClarificationRepository
from app.modules.agent.security.medical_safety import MedicalSafetyPolicy, TriageStatus
from app.modules.agent.tools.user.clinical import AssessSymptomSafetyTool
from app.modules.agent.tools.user.clarification import RequestClarificationTool
from app.modules.agent.schemas.tools import ToolExecutionStatus
from app.modules.agent.orchestrator import AgentOrchestrator
from app.modules.agent.schemas.chat import SessionType, StreamEventType
from app.common.enums import UserRole

@pytest.mark.asyncio
async def test_mild_allergy_triggers_clarification_and_terminates():
    """
    Guarantees that vague symptom queries (e.g. 'mild allergy, what should I take?')
    generate structured clarification questions and TERMINATE the agent turn immediately
    without prescribing or searching medicines.
    """
    mock_db = MagicMock()
    mock_db.agent_clarifications.insert_one = AsyncMock()

    tool = AssessSymptomSafetyTool(mock_db)

    res = await tool.execute(
        arguments={"symptoms_description": "having a mild allergy, what should I take?"},
        caller_id="usr_patient_1",
        caller_role=UserRole.USER.value,
        session_id="ses_allergy_test",
    )

    # 1. Must return CLARIFICATION_REQUIRED status
    assert res.status == ToolExecutionStatus.CLARIFICATION_REQUIRED
    assert res.requires_clarification is True
    assert res.clarification_payload is not None

    payload = res.clarification_payload
    assert payload["clarification_id"] is not None
    assert len(payload["questions"]) >= 2

    # Check question schema
    question_ids = [q["id"] for q in payload["questions"]]
    assert "symptoms" in question_ids
    assert "duration" in question_ids

    # 2. Verify MongoDB insertion occurred
    mock_db.agent_clarifications.insert_one.assert_called_once()

@pytest.mark.asyncio
async def test_clarification_repository_validation_and_consumption():
    """
    Guarantees that valid clarification submissions succeed and transition state to SUBMITTED atomically.
    """
    mock_db = MagicMock()
    repo = AgentClarificationRepository(mock_db)

    # Mock stored pending clarification document
    mock_doc = {
        "id": "clarif_123",
        "user_id": "usr_patient_1",
        "session_id": "ses_456",
        "status": "PENDING",
        "questions": [
            {
                "id": "symptoms",
                "type": "multi_select",
                "question": "What symptoms are you experiencing?",
                "required": True,
                "options": [
                    {"id": "sneezing", "label": "Sneezing"},
                    {"id": "itchy_eyes", "label": "Itchy eyes"},
                    {"id": "hives", "label": "Hives"},
                ],
            },
            {
                "id": "duration",
                "type": "single_select",
                "question": "How long have you had symptoms?",
                "required": True,
                "options": [
                    {"id": "today", "label": "Today"},
                    {"id": "few_days", "label": "Few days"},
                ],
            },
        ],
        "created_at": "2026-08-30T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    mock_db.agent_clarifications.find_one = AsyncMock(return_value=mock_doc)
    mock_db.agent_clarifications.find_one_and_update = AsyncMock(return_value={
        **mock_doc,
        "status": "SUBMITTED",
        "answers": [
            {"question_id": "symptoms", "question": "What symptoms are you experiencing?", "value": ["sneezing", "itchy_eyes"]},
            {"question_id": "duration", "question": "How long have you had symptoms?", "value": "few_days"},
        ],
    })

    valid_answers = [
        {"question_id": "symptoms", "value": ["sneezing", "itchy_eyes"]},
        {"question_id": "duration", "value": "few_days"},
    ]

    is_valid, err, updated = await repo.validate_and_consume_clarification(
        clarification_id="clarif_123",
        user_id="usr_patient_1",
        session_id="ses_456",
        submitted_answers=valid_answers,
    )

    assert is_valid is True
    assert err is None
    assert updated["status"] == "SUBMITTED"
    assert len(updated["answers"]) == 2

@pytest.mark.asyncio
async def test_clarification_rejects_invalid_option():
    """
    Guarantees that submitting unlisted options for a closed choice question is rejected.
    """
    mock_db = MagicMock()
    repo = AgentClarificationRepository(mock_db)

    mock_doc = {
        "id": "clarif_inv",
        "user_id": "usr_patient_1",
        "session_id": "ses_456",
        "status": "PENDING",
        "questions": [
            {
                "id": "duration",
                "type": "single_select",
                "question": "Duration?",
                "required": True,
                "options": [{"id": "today", "label": "Today"}],
                "allow_custom_input": False,
            }
        ],
        "expires_at": "2099-01-01T00:00:00Z",
    }
    mock_db.agent_clarifications.find_one = AsyncMock(return_value=mock_doc)

    is_valid, err, updated = await repo.validate_and_consume_clarification(
        clarification_id="clarif_inv",
        user_id="usr_patient_1",
        session_id="ses_456",
        submitted_answers=[{"question_id": "duration", "value": "invalid_option_xyz"}],
    )

    assert is_valid is False
    assert "Invalid option" in err
    assert updated is None

@pytest.mark.asyncio
async def test_clarification_ownership_and_replay_security():
    """
    Guarantees cross-user access, session mismatch, and replaying resolved clarifications are blocked.
    """
    mock_db = MagicMock()
    repo = AgentClarificationRepository(mock_db)

    mock_doc = {
        "id": "clarif_sec",
        "user_id": "usr_alice",
        "session_id": "ses_alice_1",
        "status": "PENDING",
        "questions": [{"id": "q1", "type": "text", "question": "Q1", "required": False}],
        "expires_at": "2099-01-01T00:00:00Z",
    }
    mock_db.agent_clarifications.find_one = AsyncMock(return_value=mock_doc)

    # 1. User mismatch
    is_valid, err, _ = await repo.validate_and_consume_clarification(
        clarification_id="clarif_sec",
        user_id="usr_bob_attacker",
        session_id="ses_alice_1",
        submitted_answers=[],
    )
    assert is_valid is False
    assert "Access denied" in err

    # 2. Session mismatch
    is_valid2, err2, _ = await repo.validate_and_consume_clarification(
        clarification_id="clarif_sec",
        user_id="usr_alice",
        session_id="ses_wrong_session",
        submitted_answers=[],
    )
    assert is_valid2 is False
    assert "Access denied" in err2

    # 3. Replay prevention (Already SUBMITTED)
    mock_db.agent_clarifications.find_one = AsyncMock(return_value={**mock_doc, "status": "SUBMITTED"})
    is_valid3, err3, _ = await repo.validate_and_consume_clarification(
        clarification_id="clarif_sec",
        user_id="usr_alice",
        session_id="ses_alice_1",
        submitted_answers=[],
    )
    assert is_valid3 is False
    assert "already been submitted" in err3.lower()

@pytest.mark.asyncio
async def test_emergency_bypasses_clarification():
    """
    Guarantees critical emergency queries (breathing distress + swollen lips)
    immediately return emergency directions with ZERO clarification questions.
    """
    res = MedicalSafetyPolicy.assess_symptoms("I cannot breathe and my lips and throat are swelling rapidly")
    assert res.status == TriageStatus.EMERGENCY
    assert res.is_emergency is True
    assert res.can_recommend_medication is False
    assert res.clarification_questions is None
    assert "999" in res.guidance or "emergency" in res.guidance.lower()

@pytest.mark.asyncio
async def test_factual_queries_bypass_clarification():
    """
    Guarantees factual medicine lookup queries do not trigger clarification forms.
    """
    res1 = MedicalSafetyPolicy.assess_symptoms("What is Cetirizine 10mg used for?")
    assert res1.status == TriageStatus.GENERAL_INFORMATION
    assert res1.clarification_questions is None

    res2 = MedicalSafetyPolicy.assess_symptoms("What is the price of Napa Extra?")
    assert res2.status == TriageStatus.GENERAL_INFORMATION
    assert res2.clarification_questions is None
