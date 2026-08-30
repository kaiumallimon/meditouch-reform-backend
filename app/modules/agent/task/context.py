"""
AgentTaskContext — Persistent task state for multi-turn clinical conversations.

Stored in MongoDB (`agent_task_context` collection) to survive serverless restarts.

Key invariant:
    primary_complaint is NEVER replaced by a clarification answer.
    It can only change via an explicit update_primary_complaint() call,
    which should be triggered only when the user clearly states a new subject.
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.schemas.clarification import ClinicalContext
from app.core.logging import logger

TASK_TTL_SECONDS = 1800  # 30 minutes


class AgentTaskContextRepository:
    """
    MongoDB-persisted repository for agent task state.

    A task represents a user's ongoing clinical intent (e.g. "find out what to take for cough")
    that spans one or more clarification rounds. It preserves the original request and
    accumulates clinical context cumulatively as answers arrive.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.agent_task_context

    async def create_task(
        self,
        session_id: str,
        user_id: str,
        original_request: str,
        intent_type: str,
        primary_complaint: Optional[str],
        clarification_id: Optional[str] = None,
        ttl_seconds: int = TASK_TTL_SECONDS,
    ) -> Dict[str, Any]:
        """Creates a new active task for this session."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        clinical_context_dict: Dict[str, Any] = {}
        if primary_complaint:
            clinical_context_dict = {
                "primary_complaint": {
                    "symptom": primary_complaint,
                    "duration": None,
                    "symptom_type": None,
                    "severity": None,
                    "onset": None,
                },
                "secondary_complaints": [],
                "associated_symptoms": [],
                "relevant_history": {
                    "allergies": [],
                    "chronic_conditions": [],
                    "current_medications": [],
                },
                "red_flags": [],
                "clarification_status": "pending",
            }

        doc = {
            "task_id": task_id,
            "session_id": session_id,
            "user_id": user_id,
            "original_request": original_request,
            "intent_type": intent_type,
            "primary_complaint": primary_complaint,
            "secondary_complaints": [],
            "status": "awaiting_clarification" if clarification_id else "processing",
            "clinical_context": clinical_context_dict,
            "clarification_id": clarification_id,
            "clarification_rounds": 0,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        await self.collection.insert_one(doc)
        logger.info(
            f"[TaskContext] Created task {task_id} for user {user_id} in session {session_id} "
            f"(complaint={primary_complaint}, intent={intent_type})"
        )
        return doc

    async def get_active_task(
        self,
        session_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns the most recent non-abandoned, non-expired task for this session.
        Returns None if no active task exists (e.g. first turn or all tasks completed).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        doc = await self.collection.find_one(
            {
                "session_id": session_id,
                "user_id": user_id,
                "status": {"$in": ["awaiting_clarification", "processing"]},
                "expires_at": {"$gt": now_iso},
            },
            sort=[("created_at", -1)],
        )
        return doc

    async def get_task_by_clarification_id(
        self,
        clarification_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieves the task associated with a specific clarification ID."""
        return await self.collection.find_one({"clarification_id": clarification_id})

    async def merge_answers_into_context(
        self,
        task_id: str,
        answers: List[Dict[str, Any]],
        new_clarification_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Merges clarification answers into the task's clinical_context in an ADDITIVE way.
        The primary_complaint is never overwritten. All new answers extend the context.
        Returns the updated document.
        """
        doc = await self.collection.find_one({"task_id": task_id})
        if not doc:
            logger.warning(f"[TaskContext] Task {task_id} not found for context merge")
            return None

        # Reconstruct ClinicalContext from stored dict
        ctx_dict = doc.get("clinical_context") or {}
        try:
            ctx = ClinicalContext.model_validate(ctx_dict)
        except Exception:
            ctx = ClinicalContext()

        # Merge answers (additive, never replaces primary_complaint)
        ctx.merge_answers(answers)
        ctx.clarification_status = "completed"

        # Determine new status
        new_status = "processing" if not new_clarification_id else "awaiting_clarification"

        now_iso = datetime.now(timezone.utc).isoformat()
        updated = await self.collection.find_one_and_update(
            {"task_id": task_id},
            {
                "$set": {
                    "clinical_context": ctx.model_dump(),
                    "status": new_status,
                    "clarification_id": new_clarification_id,
                    "updated_at": now_iso,
                },
                "$inc": {"clarification_rounds": 1},
            },
            return_document=True,
        )
        logger.info(
            f"[TaskContext] Merged {len(answers)} answers into task {task_id} "
            f"(primary_complaint unchanged: {doc.get('primary_complaint')})"
        )
        return updated

    async def update_task_status(self, task_id: str, status: str) -> None:
        """Updates the task lifecycle status."""
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one(
            {"task_id": task_id},
            {"$set": {"status": status, "updated_at": now_iso}},
        )

    async def update_primary_complaint(
        self,
        task_id: str,
        new_primary_complaint: str,
        reason: str = "explicit_user_request",
    ) -> None:
        """
        Updates the primary complaint — ONLY called when the user explicitly
        switches topic (e.g. 'forget the cough, what about my headache?').
        Never called automatically from clarification answer parsing.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "primary_complaint": new_primary_complaint,
                    "updated_at": now_iso,
                },
                "$push": {
                    "topic_switch_log": {
                        "new_complaint": new_primary_complaint,
                        "reason": reason,
                        "timestamp": now_iso,
                    }
                },
            },
        )
        logger.info(
            f"[TaskContext] Primary complaint switched to '{new_primary_complaint}' in task {task_id} (reason: {reason})"
        )

    async def complete_task(self, task_id: str) -> None:
        """Marks the task as completed."""
        await self.update_task_status(task_id, "completed")

    def build_task_context_injection(self, task: Dict[str, Any]) -> str:
        """
        Builds a compact structured system injection for the LLM.
        Kept intentionally short to avoid token limit issues on small Groq quotas.
        """
        original = task.get("original_request", "")
        primary = task.get("primary_complaint", "unknown")

        lines = [
            "[ACTIVE TASK]",
            f'Original request: "{original}"',
            f"Primary complaint: {primary}",
            "Do NOT change primary complaint unless user explicitly says to.",
        ]

        ctx_dict = task.get("clinical_context") or {}
        try:
            ctx = ClinicalContext.model_validate(ctx_dict)
            ctx_str = ctx.to_context_string()
            if ctx_str and ctx_str != "No structured clinical context yet.":
                lines.append("Collected info:")
                lines.append(ctx_str)
        except Exception:
            pass

        lines.append("Continue solving the original request using all collected info above.")
        return "\n".join(lines)


