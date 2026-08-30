from typing import AsyncGenerator, List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.schemas.chat import SessionType, ChatRequest
from app.modules.agent.memory.repository import AgentMemoryRepository
from app.modules.agent.memory.session import SessionMemoryManager
from app.modules.agent.tools.registry import ToolRegistry
from app.modules.agent.security.audit import AgentAuditService
from app.modules.agent.llm.service import LLMService
from app.modules.agent.orchestrator import AgentOrchestrator

class AgentChatService:
    """High-level service coordinating memory, permissions, orchestrator, and stream generation."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = AgentMemoryRepository(db)
        self.memory = SessionMemoryManager(self.repo)
        self.registry = ToolRegistry(db)
        self.audit = AgentAuditService(db)
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
    ) -> Dict[str, Any]:
        session_type = SessionType.ADMIN if user_role in ["ADMIN", "DEVELOPER"] else SessionType.USER
        if session_id:
            session = await self.repo.get_session(session_id)
            if session and session.get("user_id") == user_id:
                return session

        title = self.memory.generate_initial_title(first_message)
        return await self.repo.create_session(user_id=user_id, session_type=session_type, title=title)

    async def stream_chat_turn(
        self,
        req: ChatRequest,
        user_id: str,
        user_role: str,
    ) -> AsyncGenerator[str, None]:
        session = await self.get_or_create_session(
            session_id=req.session_id,
            user_id=user_id,
            user_role=user_role,
            first_message=req.message,
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
        import json
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

        # Persist Assistant Response
        if assistant_full_content:
            await self.repo.add_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=assistant_full_content,
            )
