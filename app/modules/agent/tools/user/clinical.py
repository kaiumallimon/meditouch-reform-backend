from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.modules.agent.security.medical_safety import MedicalSafetyPolicy
from app.common.enums import UserRole

class AssessSymptomSafetyTool(BaseTool):
    """
    Evaluates symptoms for medical safety, emergency red flags, and triage level.
    Strictly clinical screening only - DOES NOT prescribe or recommend medications.
    """

    name = "assess_symptom_safety"
    description = (
        "Screens user-reported symptoms for emergency warning signs (e.g. breathing distress, "
        "chest pain, anaphylaxis, loss of consciousness) and provides clinical safety guidance. "
        "Does NOT recommend or prescribe medications."
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

        assessment = MedicalSafetyPolicy.assess_symptoms(symptoms_text)

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result=assessment.model_dump(),
            metadata={
                "action": "ASSESS_SYMPTOM_SAFETY",
                "triage_status": assessment.status.value,
                "is_emergency": assessment.is_emergency,
            },
        )
