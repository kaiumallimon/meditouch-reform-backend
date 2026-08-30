from typing import AsyncGenerator, List, Dict, Any, Optional
import json
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.schemas.chat import SessionType, ChatRequest
from app.modules.agent.schemas.clarification import ClarificationSubmissionRequest, ClinicalContext
from app.modules.agent.security.clarifications import AgentClarificationRepository
from app.modules.agent.task.context import AgentTaskContextRepository
from app.modules.agent.memory.repository import AgentMemoryRepository
from app.modules.agent.memory.session import SessionMemoryManager
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.security.audit import AgentAuditService
from app.modules.agent.llm.service import LLMService
from app.modules.agent.orchestrator import AgentOrchestrator
from app.core.exceptions import ForbiddenException, NotFoundException, BadRequestException
from app.core.logging import logger


class AgentChatService:
    """High-level service coordinating memory, permissions, orchestrator, and stream generation."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = AgentMemoryRepository(db)
        self.memory = SessionMemoryManager(self.repo)
        self.registry = ToolRegistry(db)
        self.audit = AgentAuditService(db)
        self.clarif_repo = AgentClarificationRepository(db)
        self.task_repo = AgentTaskContextRepository(db)
        self.llm_service = LLMService()
        self.orchestrator = AgentOrchestrator(
            llm=self.llm_service.get_provider(),
            registry=self.registry,
            audit_service=self.audit,
        )

    async def get_or_create_session(
        self,
        session_id: Optional[str],
        user_id: str,
        user_role: str,
        first_message: str,
        explicit_session_type: Optional[SessionType] = None,
    ) -> Dict[str, Any]:
        default_type = SessionType.ADMIN if user_role in ["ADMIN", "DEVELOPER"] else SessionType.USER
        target_type = explicit_session_type or default_type

        if session_id:
            session = await self.repo.get_session(session_id)
            if not session:
                raise NotFoundException(f"Chat session '{session_id}' not found.")
            if session.get("user_id") != user_id and user_role not in ["ADMIN", "DEVELOPER"]:
                raise ForbiddenException("Access denied: You do not own this chat session.")
            return session

        title = self.memory.generate_initial_title(first_message)
        return await self.repo.create_session(user_id=user_id, session_type=target_type, title=title)

    async def stream_chat_turn(
        self,
        req: ChatRequest,
        user_id: str,
        user_role: str,
        explicit_session_type: Optional[SessionType] = None,
    ) -> AsyncGenerator[str, None]:
        session = await self.get_or_create_session(
            session_id=req.session_id,
            user_id=user_id,
            user_role=user_role,
            first_message=req.message,
            explicit_session_type=explicit_session_type,
        )
        session_id = session["id"]
        session_type = SessionType(session["session_type"])

        # Persist User Message
        await self.repo.add_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=req.message,
        )

        # Emit initial session metadata event
        yield f"event: session\ndata: {json.dumps({'session_id': session_id, 'title': session.get('title')}, default=str)}\n\n"

        history = await self.memory.get_recent_messages_for_llm(session_id=session_id, window_size=6)

        assistant_full_content = ""
        async for event in self.orchestrator.execute_turn_stream(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            session_type=session_type,
            user_message=req.message,
            conversation_history=history,
            confirmation_token=req.confirmation_token,
        ):
            event_name = event.get("event", "message")
            data = event.get("data", {})
            if event_name == "done":
                assistant_full_content = data.get("full_content", "")

            yield f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

        # Persist Assistant Response (skip empty clarification turns — card IS the response)
        if assistant_full_content:
            await self.repo.add_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=assistant_full_content,
            )

    async def stream_clarification_submission(
        self,
        session_id: str,
        clarification_id: str,
        submission: ClarificationSubmissionRequest,
        user_id: str,
        user_role: str,
        explicit_session_type: Optional[SessionType] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Intent-preserving clarification submission handler.

        This is the core fix for the original intent bug.

        Workflow:
        1. Validate & atomically consume clarification (ownership, options, TTL).
        2. Restore original_message and primary_complaint from clarification record.
        3. Find or create AgentTaskContext and merge answers additively.
        4. Build task_context_injection string (injected as system message).
        5. Start new agent turn with ORIGINAL REQUEST as user_message.
           NOT with the answer text — that would lose intent.
        6. Persist both the user's formatted answers AND the assistant response.
        """
        session = await self.get_or_create_session(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            first_message="",
            explicit_session_type=explicit_session_type,
        )
        session_type = SessionType(session["session_type"])

        # ── Step 1: Validate and consume clarification ────────────────────────
        is_valid, err_msg, updated_clarif = await self.clarif_repo.validate_and_consume_clarification(
            clarification_id=clarification_id,
            user_id=user_id,
            session_id=session_id,
            submitted_answers=[a.model_dump() for a in submission.answers],
        )

        if not is_valid or not updated_clarif:
            if "Access denied" in (err_msg or ""):
                raise ForbiddenException(err_msg or "Access denied to clarification.")
            raise BadRequestException(err_msg or "Invalid clarification submission.")

        # ── Step 2: Restore original intent from clarification record ─────────
        original_message = updated_clarif.get("original_message") or ""
        primary_complaint = updated_clarif.get("primary_complaint")
        stored_clinical_context = updated_clarif.get("clinical_context") or {}
        stored_task_id = updated_clarif.get("task_id")
        intent_type = updated_clarif.get("intent_type", "symptom_medication_request")

        validated_answers = updated_clarif.get("answers", [])

        logger.info(
            f"[ClarifSubmission] Restoring intent: original_message='{original_message[:60]}', "
            f"primary_complaint={primary_complaint}, answers={len(validated_answers)}"
        )

        # ── Step 3: Load or create AgentTaskContext and merge answers ─────────
        task = None
        if stored_task_id:
            task = await self.task_repo.get_task_by_clarification_id(clarification_id)

        if not task:
            task = await self.task_repo.get_active_task(session_id=session_id, user_id=user_id)

        if task:
            # Merge answers additively into existing task context
            task = await self.task_repo.merge_answers_into_context(
                task_id=task["task_id"],
                answers=validated_answers,
            )
        else:
            # Create a new task context (first clarification for this session)
            task = await self.task_repo.create_task(
                session_id=session_id,
                user_id=user_id,
                original_request=original_message,
                intent_type=intent_type,
                primary_complaint=primary_complaint,
                clarification_id=None,  # Just submitted
                ttl_seconds=1800,
            )
            # Merge the submitted answers into the newly created task
            task = await self.task_repo.merge_answers_into_context(
                task_id=task["task_id"],
                answers=validated_answers,
            )

        # ── Step 4: Build structured task context injection ───────────────────
        task_context_injection = ""
        if task:
            task_context_injection = self.task_repo.build_task_context_injection(task)

        # ── Step 5: Persist the user's formatted answers into chat history ────
        # This is for display in the chat UI only — NOT sent as user_message to the LLM
        answer_lines = []
        for a in validated_answers:
            val = a.get("value")
            val_formatted = ", ".join(val) if isinstance(val, list) else str(val)
            answer_lines.append(f"• **{a.get('question')}**: {val_formatted}")

        user_answer_display_text = (
            "📋 **My answers:**\n" + "\n".join(answer_lines)
        ) if answer_lines else "Answers submitted."

        await self.repo.add_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=user_answer_display_text,
            tool_results_metadata={
                "clarification_id": clarification_id,
                "original_message": original_message,
                "primary_complaint": primary_complaint,
                "answers": validated_answers,
            },
        )

        # Emit initial session metadata event
        yield f"event: session\ndata: {json.dumps({'session_id': session_id, 'title': session.get('title')}, default=str)}\n\n"

        # Use a slightly larger history window to include the clarification question message
        history = await self.memory.get_recent_messages_for_llm(session_id=session_id, window_size=8)

        # ── Step 6: Start new agent turn with ORIGINAL REQUEST as user_message ─
        # This is the critical fix: we pass original_message (the user's initial question),
        # NOT the answer text. The task_context_injection carries all the structured context.
        turn_message = original_message if original_message else user_answer_display_text

        logger.info(
            f"[ClarifSubmission] Starting continuation turn: "
            f"user_message='{turn_message[:60]}', "
            f"task_context_injection={'yes' if task_context_injection else 'no'}"
        )

        assistant_full_content = ""
        async for event in self.orchestrator.execute_turn_stream(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            session_type=session_type,
            user_message=turn_message,
            conversation_history=history,
            task_context_injection=task_context_injection,
            task_context=task,
        ):
            event_name = event.get("event", "message")
            data = event.get("data", {})
            if event_name == "done":
                assistant_full_content = data.get("full_content", "")

            yield f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

        # Persist Assistant Response
        if assistant_full_content:
            await self.repo.add_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=assistant_full_content,
            )

        # Update task to completed if agent provided a final answer
        if assistant_full_content and task:
            await self.task_repo.update_task_status(task["task_id"], "completed")
