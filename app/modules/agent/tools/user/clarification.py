from typing import Dict, Any, Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.modules.agent.security.clarifications import AgentClarificationRepository
from app.common.enums import UserRole

class RequestClarificationTool(BaseTool):
    """
    Allows the agent to ask the user structured clarification questions.
    Executing this tool pauses the agent loop and returns an interactive form to the user.
    """

    name = "request_clarification"
    description = (
        "Requests structured clarification from the user when critical information is missing "
        "(e.g. specific symptoms, duration, or choosing between ambiguous candidate entities). "
        "Halts the current turn immediately until the user provides their answers."
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
            "message": {
                "type": "string",
                "description": "Brief introductory explanation of why clarification is needed.",
            },
            "questions": {
                "type": "array",
                "description": "List of structured questions (up to 5 questions).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Unique identifier for the question (e.g. 'symptoms', 'duration', 'entity_id')"},
                        "type": {
                            "type": "string",
                            "enum": ["single_select", "multi_select", "text", "free_text", "number", "boolean", "date", "entity_select"],
                            "description": "UI input type",
                        },
                        "question": {"type": "string", "description": "The question prompt to display"},
                        "required": {"type": "boolean", "default": True},
                        "options": {
                            "type": "array",
                            "description": "Selectable choices for single_select, multi_select, or entity_select",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "Option value identifier"},
                                    "label": {"type": "string", "description": "Display label for the choice"},
                                    "subtitle": {"type": "string", "description": "Optional secondary description"},
                                },
                                "required": ["id", "label"],
                            },
                        },
                        "allow_custom_input": {"type": "boolean", "default": False},
                        "placeholder": {"type": "string", "description": "Placeholder text for text inputs"},
                    },
                    "required": ["id", "type", "question"],
                },
            },
        },
        "required": ["message", "questions"],
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
        message = arguments.get("message", "I need a little more information before I can safely answer.")
        questions = arguments.get("questions", [])

        if not questions or not isinstance(questions, list):
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message="At least one clarification question is required.",
            )

        clarif_id = "clarif_sim"
        if self.db is not None:
            repo = AgentClarificationRepository(self.db)
            clarif_id = await repo.create_pending_clarification(
                user_id=caller_id,
                session_id=session_id,
                message=message,
                questions=questions,
            )

        payload = {
            "clarification_id": clarif_id,
            "message": message,
            "questions": questions,
            "submission": {
                "action": "submit_clarification",
                "session_id": session_id,
                "clarification_id": clarif_id,
            },
        }

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CLARIFICATION_REQUIRED,
            result=payload,
            requires_clarification=True,
            clarification_id=clarif_id,
            clarification_payload=payload,
            metadata={"action": "REQUEST_CLARIFICATION", "question_count": len(questions)},
        )

