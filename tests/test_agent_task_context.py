"""
Automated test suite for the agent task context and intent preservation fixes.

Tests validate the full invariant:
    ORIGINAL REQUEST + CLARIFICATION ANSWERS = CONTINUED TASK
    NOT: LATEST ANSWER = NEW TASK
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.modules.agent.schemas.clarification import ClinicalContext, PrimaryComplaintContext, AssociatedSymptom
from app.modules.agent.security.clarifications import AgentClarificationRepository
from app.modules.agent.security.medical_safety import MedicalSafetyPolicy, TriageStatus
from app.modules.agent.tools.user.clinical import AssessSymptomSafetyTool
from app.modules.agent.schemas.tools import ToolExecutionStatus
from app.modules.agent.task.context import AgentTaskContextRepository


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Cough query correctly identifies primary_complaint = "cough"
# ─────────────────────────────────────────────────────────────────────────────
def test_cough_query_identifies_primary_complaint():
    """
    User: "I'm having cough, what medicine should I take?"
    Expected: primary_complaint = "cough", INSUFFICIENT_INFORMATION, cough-specific questions
    """
    res = MedicalSafetyPolicy.assess_symptoms("I'm having cough, what medicine should I take?")
    assert res.status == TriageStatus.INSUFFICIENT_INFORMATION
    assert res.primary_complaint == "cough"
    assert res.is_emergency is False
    assert res.can_recommend_medication is False
    assert res.clarification_questions is not None
    q_ids = [q["id"] for q in res.clarification_questions]
    assert "duration" in q_ids
    assert "cough_type" in q_ids
    assert "severity" in q_ids


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Clarification answers preserve primary_complaint = "cough"
# ─────────────────────────────────────────────────────────────────────────────
def test_clarification_answers_preserve_primary_complaint():
    """
    Submit: duration=less_than_3_days
    Expected: primary_complaint remains "cough" — not "duration" or any answer value
    """
    ctx = ClinicalContext(
        primary_complaint=PrimaryComplaintContext(symptom="cough"),
    )
    ctx.merge_answers([
        {"question_id": "duration", "question": "How long?", "value": "less_than_3_days"},
    ])
    assert ctx.primary_complaint is not None
    assert ctx.primary_complaint.symptom == "cough"
    assert ctx.primary_complaint.duration == "less_than_3_days"
    # primary complaint was NOT replaced
    assert ctx.primary_complaint.symptom != "less_than_3_days"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Fever as a clarification answer does NOT become primary complaint
# ─────────────────────────────────────────────────────────────────────────────
def test_fever_answer_does_not_replace_primary_cough():
    """
    Submit: fever=true (via associated_symptoms answer)
    Expected: primary_complaint remains "cough", fever in associated_symptoms
    """
    ctx = ClinicalContext(
        primary_complaint=PrimaryComplaintContext(symptom="cough"),
    )
    ctx.merge_answers([
        {"question_id": "duration", "question": "How long?", "value": "less_than_3_days"},
        {"question_id": "cough_type", "question": "Dry or productive?", "value": "dry"},
        {"question_id": "severity", "question": "Severity?", "value": "moderate"},
        {"question_id": "associated_symptoms", "question": "Other symptoms?", "value": ["fever", "runny_nose"]},
    ])
    assert ctx.primary_complaint.symptom == "cough"  # still cough
    fever_syms = [s.symptom for s in ctx.associated_symptoms]
    assert "fever" in fever_syms
    assert "runny_nose" in fever_syms


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Secondary symptom mention stays as secondary
# ─────────────────────────────────────────────────────────────────────────────
def test_secondary_symptom_stays_secondary():
    """
    User mentions "I also have a mild headache."
    Expected: primary_complaint = "cough", headache added to associated_symptoms
    """
    ctx = ClinicalContext(
        primary_complaint=PrimaryComplaintContext(symptom="cough"),
    )
    ctx.merge_answers([
        {"question_id": "associated_symptoms", "question": "Other?", "value": ["mild headache"]},
    ])
    assert ctx.primary_complaint.symptom == "cough"
    assert any("headache" in s.symptom.lower() for s in ctx.associated_symptoms)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Explicit subject change — primary complaint can only be updated explicitly
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_explicit_task_switch_updates_primary_complaint():
    """
    User: "Forget the cough. What should I take for my headache?"
    Expected: update_primary_complaint() is called, primary_complaint = "headache"
    """
    mock_db = MagicMock()
    mock_db.agent_task_context.find_one_and_update = AsyncMock(return_value={
        "task_id": "task_001",
        "primary_complaint": "headache",
        "status": "processing",
    })
    mock_db.agent_task_context.update_one = AsyncMock()

    repo = AgentTaskContextRepository(mock_db)
    await repo.update_primary_complaint(
        task_id="task_001",
        new_primary_complaint="headache",
        reason="explicit_user_request",
    )
    mock_db.agent_task_context.update_one.assert_called_once()
    call_args = mock_db.agent_task_context.update_one.call_args
    assert call_args[0][1]["$set"]["primary_complaint"] == "headache"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: Temperature unit validation — 100C is flagged
# ─────────────────────────────────────────────────────────────────────────────
def test_suspicious_temperature_celsius_triggers_clarification():
    """
    User: "in tongue, fever around 100C"
    Expected: INSUFFICIENT_INFORMATION with temperature_clarification question, not silent normalization
    """
    res = MedicalSafetyPolicy.assess_symptoms("I have a fever around 100C")
    assert res.status == TriageStatus.INSUFFICIENT_INFORMATION
    assert res.recommended_action == "CLARIFY_TEMPERATURE_UNIT"
    assert res.clarification_questions is not None
    q_ids = [q["id"] for q in res.clarification_questions]
    assert "temperature_clarification" in q_ids

    # 38.5C should NOT be flagged (valid Celsius range)
    res2 = MedicalSafetyPolicy.assess_symptoms("I have a fever of 38.5C")
    assert res2.recommended_action != "CLARIFY_TEMPERATURE_UNIT"

    # 101F should NOT be flagged (Fahrenheit text, no 'C' unit)
    res3 = MedicalSafetyPolicy.assess_symptoms("I have 101 degrees fever")
    assert res3.recommended_action != "CLARIFY_TEMPERATURE_UNIT"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Duplicate identical tool call returns cached result
# ─────────────────────────────────────────────────────────────────────────────
def test_args_hash_dedup():
    """
    Identical tool_name + args produce the same hash.
    Different args produce different hashes.
    """
    from app.modules.agent.orchestrator import _args_hash
    h1 = _args_hash("search_medicines", {"query": "napa"})
    h2 = _args_hash("search_medicines", {"query": "napa"})
    h3 = _args_hash("search_medicines", {"query": "paracetamol"})
    h4 = _args_hash("assess_symptom_safety", {"query": "napa"})
    assert h1 == h2           # same tool + same args → same hash
    assert h1 != h3           # different args → different hash
    assert h1 != h4           # different tool → different hash


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8: Clarification event terminates turn (no content after it)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_clarification_event_is_terminal():
    """
    When AssessSymptomSafetyTool returns CLARIFICATION_REQUIRED,
    the result must have requires_clarification=True and a clarification_payload.
    """
    mock_db = MagicMock()
    mock_db.agent_clarifications.insert_one = AsyncMock()
    tool = AssessSymptomSafetyTool(mock_db)
    res = await tool.execute(
        arguments={"symptoms_description": "I'm having cough, what medicine should I take?"},
        caller_id="user_001",
        caller_role="USER",
        session_id="ses_001",
    )
    assert res.status == ToolExecutionStatus.CLARIFICATION_REQUIRED
    assert res.requires_clarification is True
    assert res.clarification_payload is not None
    assert "questions" in res.clarification_payload
    # Confirm original_message is preserved in the clarification (stored in DB)
    insert_call = mock_db.agent_clarifications.insert_one.call_args[0][0]
    assert insert_call["primary_complaint"] == "cough"
    assert "cough" in insert_call["original_message"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9: Clarification submission receives full context (not just latest answer)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_clarification_submission_carries_original_request():
    """
    Submission must return original_message and primary_complaint from the stored record.
    """
    mock_db = MagicMock()
    repo = AgentClarificationRepository(mock_db)
    mock_doc = {
        "id": "clarif_999",
        "user_id": "user_001",
        "session_id": "ses_001",
        "status": "PENDING",
        "original_message": "I'm having cough, what medicine should I take?",
        "primary_complaint": "cough",
        "clinical_context": {},
        "questions": [
            {
                "id": "duration",
                "type": "single_select",
                "question": "How long?",
                "required": True,
                "options": [{"id": "less_than_3_days", "label": "Less than 3 days"}],
            }
        ],
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    mock_db.agent_clarifications.find_one = AsyncMock(return_value=mock_doc)
    mock_db.agent_clarifications.find_one_and_update = AsyncMock(return_value={
        **mock_doc,
        "status": "SUBMITTED",
        "answers": [{"question_id": "duration", "question": "How long?", "value": "less_than_3_days"}],
    })

    is_valid, err, updated = await repo.validate_and_consume_clarification(
        clarification_id="clarif_999",
        user_id="user_001",
        session_id="ses_001",
        submitted_answers=[{"question_id": "duration", "value": "less_than_3_days"}],
    )

    assert is_valid is True
    # original_message and primary_complaint must survive submission
    assert updated["original_message"] == "I'm having cough, what medicine should I take?"
    assert updated["primary_complaint"] == "cough"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10: Task context recovers from MongoDB after serverless restart
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_task_context_recovered_from_mongodb():
    """
    Calling get_active_task() after a simulated restart must return the persisted task,
    including original_request and primary_complaint.
    """
    mock_db = MagicMock()
    mock_task = {
        "task_id": "task_reboot",
        "session_id": "ses_reboot",
        "user_id": "user_reboot",
        "original_request": "I'm having cough, what medicine should I take?",
        "primary_complaint": "cough",
        "status": "awaiting_clarification",
        "clinical_context": {"primary_complaint": {"symptom": "cough"}},
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    # Simulate MongoDB find_one returning the persisted doc (as if memory was wiped)
    mock_db.agent_task_context.find_one = AsyncMock(return_value=mock_task)
    repo = AgentTaskContextRepository(mock_db)

    recovered = await repo.get_active_task(session_id="ses_reboot", user_id="user_reboot")
    assert recovered is not None
    assert recovered["original_request"] == "I'm having cough, what medicine should I take?"
    assert recovered["primary_complaint"] == "cough"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11: ClinicalContext.to_context_string() produces readable injection
# ─────────────────────────────────────────────────────────────────────────────
def test_clinical_context_to_string():
    ctx = ClinicalContext(
        primary_complaint=PrimaryComplaintContext(
            symptom="cough",
            duration="less_than_3_days",
            symptom_type="dry",
            severity="moderate",
        ),
        associated_symptoms=[
            AssociatedSymptom(symptom="fever", value=True),
        ],
        secondary_complaints=[],
    )
    ctx.relevant_history.allergies = ["dust"]

    text = ctx.to_context_string()
    assert "cough" in text
    assert "less_than_3_days" in text
    assert "dry" in text
    assert "moderate" in text
    assert "fever" in text
    assert "dust" in text


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12: AgentTaskContextRepository.build_task_context_injection()
# ─────────────────────────────────────────────────────────────────────────────
def test_task_context_injection_string():
    mock_db = MagicMock()
    repo = AgentTaskContextRepository(mock_db)

    task = {
        "task_id": "t1",
        "original_request": "I'm having cough, what medicine should I take?",
        "primary_complaint": "cough",
        "clinical_context": {
            "primary_complaint": {
                "symptom": "cough",
                "duration": "less_than_3_days",
                "symptom_type": "dry",
                "severity": "moderate",
            },
            "associated_symptoms": [{"symptom": "fever", "value": True}],
            "secondary_complaints": [],
            "relevant_history": {"allergies": ["dust"], "chronic_conditions": [], "current_medications": []},
            "red_flags": [],
            "clarification_status": "completed",
        },
        "secondary_complaints": [],
    }
    injection = repo.build_task_context_injection(task)
    assert "ACTIVE TASK" in injection
    assert "I'm having cough, what medicine should I take?" in injection
    assert "cough" in injection
    assert "primary complaint" in injection.lower()
    assert "primary complaint" in injection.lower()
