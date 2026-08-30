import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.schemas.clarification import (
    DEFAULT_CLARIFICATION_TTL_SECONDS,
    MAX_QUESTIONS_PER_CLARIFICATION,
    MAX_OPTION_COUNT,
    QuestionType,
)
from app.core.logging import logger

class AgentClarificationRepository:
    """
    MongoDB-persisted repository for interactive clarification questions.
    Guarantees atomic, single-use, user-bound, and session-bound validation
    that survives serverless / Vercel restarts.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.agent_clarifications

    async def create_pending_clarification(
        self,
        user_id: str,
        session_id: str,
        message: str,
        questions: List[Dict[str, Any]],
        ttl_seconds: int = DEFAULT_CLARIFICATION_TTL_SECONDS,
    ) -> str:
        # Enforce question limit
        bounded_questions = questions[:MAX_QUESTIONS_PER_CLARIFICATION]
        # Enforce option limit per question
        for q in bounded_questions:
            if "options" in q and isinstance(q["options"], list):
                q["options"] = q["options"][:MAX_OPTION_COUNT]

        clarification_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        doc = {
            "id": clarification_id,
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "questions": bounded_questions,
            "status": "PENDING",
            "answers": None,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "submitted_at": None,
        }

        await self.collection.insert_one(doc)
        logger.info(f"Agent Clarification created: [{clarification_id}] for user {user_id} in session {session_id} with {len(bounded_questions)} questions")
        return clarification_id

    async def get_pending_clarification(self, clarification_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"id": clarification_id})

    async def validate_and_consume_clarification(
        self,
        clarification_id: str,
        user_id: str,
        session_id: str,
        submitted_answers: List[Dict[str, Any]],
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validates user submission against schema constraints and atomically marks clarification SUBMITTED.
        """
        doc = await self.collection.find_one({"id": clarification_id})
        if not doc:
            return False, f"Clarification '{clarification_id}' not found.", None

        # 1. Ownership & Session binding
        if doc.get("user_id") != user_id and doc.get("user_id") not in ["guest_user", "anonymous"]:
            logger.warning(f"Clarification ownership mismatch for {clarification_id}: expected {doc.get('user_id')}, got {user_id}")
            return False, "Access denied: Clarification belongs to a different user.", None

        if doc.get("session_id") != session_id:
            logger.warning(f"Clarification session mismatch for {clarification_id}: expected {doc.get('session_id')}, got {session_id}")
            return False, "Access denied: Clarification belongs to a different session.", None

        # 2. Status check (Replay Prevention)
        if doc.get("status") != "PENDING":
            return False, f"Clarification has already been {doc.get('status', 'resolved').lower()}.", None

        # 3. Expiration check
        expires_at_str = doc.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now(timezone.utc) > expires_at:
                    await self.collection.update_one({"id": clarification_id}, {"$set": {"status": "EXPIRED"}})
                    return False, "Clarification request has expired. Please state your query again.", None
            except Exception:
                pass

        # 4. Validate Question IDs and Answer Constraints
        questions_map = {q["id"]: q for q in doc.get("questions", [])}
        validated_answers = []
        submitted_question_ids = set()

        for ans in submitted_answers:
            qid = ans.get("question_id")
            val = ans.get("value")

            if qid not in questions_map:
                return False, f"Invalid question ID: '{qid}'.", None

            q_def = questions_map[qid]
            q_type = q_def.get("type", "single_select")
            allowed_opts = {opt["id"] for opt in q_def.get("options", [])} if "options" in q_def and q_def["options"] else set()
            allow_custom = q_def.get("allow_custom_input", False)

            # Type & Option validation
            if q_type in [QuestionType.SINGLE_SELECT.value, QuestionType.ENTITY_SELECT.value]:
                if not isinstance(val, str) or not val.strip():
                    return False, f"Question '{qid}' requires a non-empty string value.", None
                val_str = val.strip()
                if allowed_opts and val_str not in allowed_opts and not allow_custom:
                    return False, f"Invalid option '{val_str}' for question '{qid}'. Allowed: {list(allowed_opts)}", None
                validated_answers.append({"question_id": qid, "question": q_def["question"], "value": val_str})

            elif q_type == QuestionType.MULTI_SELECT.value:
                if not isinstance(val, list) or not val:
                    return False, f"Question '{qid}' requires a non-empty list of selected values.", None
                sanitized_list = []
                for item in val:
                    item_str = str(item).strip()
                    if allowed_opts and item_str not in allowed_opts and not allow_custom:
                        return False, f"Invalid option '{item_str}' for multi-select question '{qid}'. Allowed: {list(allowed_opts)}", None
                    sanitized_list.append(item_str)
                validated_answers.append({"question_id": qid, "question": q_def["question"], "value": sanitized_list})

            elif q_type in [QuestionType.TEXT.value, QuestionType.FREE_TEXT.value]:
                val_str = str(val).strip() if val is not None else ""
                max_len = q_def.get("max_length", 500) or 500
                if len(val_str) > max_len:
                    return False, f"Answer for question '{qid}' exceeds maximum length of {max_len} characters.", None
                validated_answers.append({"question_id": qid, "question": q_def["question"], "value": val_str})

            elif q_type == QuestionType.NUMBER.value:
                try:
                    num_val = float(val)
                except (ValueError, TypeError):
                    return False, f"Question '{qid}' requires a numeric value.", None
                if q_def.get("min_value") is not None and num_val < q_def["min_value"]:
                    return False, f"Value for '{qid}' must be at least {q_def['min_value']}.", None
                if q_def.get("max_value") is not None and num_val > q_def["max_value"]:
                    return False, f"Value for '{qid}' must be at most {q_def['max_value']}.", None
                validated_answers.append({"question_id": qid, "question": q_def["question"], "value": num_val})

            elif q_type == QuestionType.BOOLEAN.value:
                bool_val = bool(val)
                validated_answers.append({"question_id": qid, "question": q_def["question"], "value": bool_val})

            else:
                validated_answers.append({"question_id": qid, "question": q_def["question"], "value": str(val)})

            submitted_question_ids.add(qid)

        # Verify required questions
        for qid, q_def in questions_map.items():
            if q_def.get("required", True) and qid not in submitted_question_ids:
                return False, f"Required question '{q_def['question']}' (id: '{qid}') is missing.", None

        # 5. Atomically transition state to SUBMITTED
        now_iso = datetime.now(timezone.utc).isoformat()
        updated_doc = await self.collection.find_one_and_update(
            {
                "id": clarification_id,
                "status": "PENDING",
            },
            {
                "$set": {
                    "status": "SUBMITTED",
                    "answers": validated_answers,
                    "submitted_at": now_iso,
                }
            },
            return_document=True
        )

        if not updated_doc:
            return False, "Failed to submit clarification: state has changed or already submitted.", None

        return True, None, updated_doc

