from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.modules.agent.security.medical_safety import MedicalSafetyPolicy, TriageStatus
from app.modules.agent.security.clarifications import AgentClarificationRepository
from app.common.enums import UserRole

class AssessSymptomSafetyTool(BaseTool):
    """
    Evaluates symptoms for medical safety, emergency red flags, and triage level.
    Strictly clinical screening only — DOES NOT prescribe or recommend medications.

    Accepts optional context parameters so that continuation runs after clarification
    do not restart the assessment from scratch, but build on existing clinical context.

    If information is insufficient, initiates structured clarification and halts.
    """

    name = "assess_symptom_safety"
    description = (
        "Screens user-reported symptoms for emergency warning signs (e.g. breathing distress, "
        "chest pain, anaphylaxis, loss of consciousness) and provides clinical safety guidance. "
        "Does NOT recommend or prescribe medications. "
        "When called after clarification answers, pass 'original_message' and 'clinical_context' "
        "to continue the original assessment rather than starting fresh."
    )
    capability = ToolCapability.MEDICAL_TRIAGE
    roles_allowed = [
        UserRole.USER.value,
        UserRole.DOCTOR.value,
        UserRole.NURSE.value,
        UserRole.ADMIN.value,
        UserRole.DEVELOPER.value,
    ]
    is_mutation = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "symptoms_description": {
                "type": "string",
                "description": "The user's reported symptoms or health concerns to screen for emergency signs.",
            },
            "original_message": {
                "type": "string",
                "description": (
                    "Optional. The user's ORIGINAL request (e.g. 'I have a cough, what should I take?'). "
                    "Provide this when continuing after a clarification round so the original intent is preserved."
                ),
            },
            "primary_complaint": {
                "type": "string",
                "description": (
                    "Optional. The already-identified primary symptom (e.g. 'cough', 'fever', 'headache'). "
                    "Providing this prevents re-classification of the primary complaint from secondary symptoms."
                ),
            },
            "clinical_context": {
                "type": "object",
                "description": (
                    "Optional. Existing clinical context dict from prior clarification rounds. "
                    "Used to skip already-answered questions and prevent redundant clarifications."
                ),
            },
        },
        "required": ["symptoms_description"],
    }

    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        self.db = db

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
        # Task context injected by the orchestrator for continuation runs
        task_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        symptoms_text = arguments.get("symptoms_description", "").strip()
        if not symptoms_text:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message="Symptoms description is required for safety assessment.",
            )

        # Extract intent preservation fields from arguments (continuation run)
        original_message = arguments.get("original_message") or symptoms_text
        primary_complaint_override = arguments.get("primary_complaint")
        clinical_context_dict = arguments.get("clinical_context")

        # If a task_context was injected by the orchestrator, prefer those values
        if task_context:
            if not original_message or original_message == symptoms_text:
                original_message = task_context.get("original_request", original_message)
            if not primary_complaint_override:
                primary_complaint_override = task_context.get("primary_complaint")
            if not clinical_context_dict:
                clinical_context_dict = task_context.get("clinical_context")

        assessment = MedicalSafetyPolicy.assess_symptoms(
            user_text=symptoms_text,
            clinical_context=clinical_context_dict,
        )

        # Override primary_complaint from assessment with the preserved one if available
        # (prevents secondary symptoms from overwriting the original primary complaint)
        effective_primary = primary_complaint_override or assessment.primary_complaint

        # If clarification is required for vague symptoms, persist state and mark terminal clarification
        if assessment.status == TriageStatus.INSUFFICIENT_INFORMATION and assessment.clarification_questions:
            clarif_id = "clarif_sim"
            if self.db is not None:
                repo = AgentClarificationRepository(self.db)
                clarif_id = await repo.create_pending_clarification(
                    user_id=caller_id,
                    session_id=session_id,
                    message=assessment.guidance,
                    questions=assessment.clarification_questions,
                    # Intent preservation fields
                    original_message=original_message,
                    primary_complaint=effective_primary,
                    clinical_context=clinical_context_dict or {},
                    intent_type="symptom_medication_request",
                )

            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.CLARIFICATION_REQUIRED,
                result={
                    "status": assessment.status.value,
                    "guidance": assessment.guidance,
                    "clarification_id": clarif_id,
                    "questions": assessment.clarification_questions,
                    "primary_complaint": effective_primary,
                },
                requires_clarification=True,
                clarification_id=clarif_id,
                clarification_payload={
                    "clarification_id": clarif_id,
                    "message": assessment.guidance,
                    "questions": assessment.clarification_questions,
                    "submission": {
                        "action": "submit_clarification",
                        "session_id": session_id,
                        "clarification_id": clarif_id,
                    },
                },
                metadata={
                    "action": "ASSESS_SYMPTOM_SAFETY",
                    "triage_status": assessment.status.value,
                    "is_emergency": False,
                    "primary_complaint": effective_primary,
                    "original_message": original_message,
                },
            )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={
                **assessment.model_dump(),
                "primary_complaint": effective_primary,
            },
            metadata={
                "action": "ASSESS_SYMPTOM_SAFETY",
                "triage_status": assessment.status.value,
                "is_emergency": assessment.is_emergency,
                "primary_complaint": effective_primary,
            },
        )
