from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.core.security import get_optional_user_payload
from app.common.responses import APIResponse
from app.common.enums import UserRole
from app.modules.agent.schemas.chat import (
    ChatRequest,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatMessageResponse,
    SessionType,
)
from app.modules.agent.service import AgentChatService

router = APIRouter(prefix="/chat", tags=["Agentic AI Assistant"])

def get_agent_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> AgentChatService:
    return AgentChatService(db)

@router.post("/stream")
async def stream_chat(
    req: ChatRequest,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """
    Real-time Server-Sent Events (SSE) streaming endpoint for the agentic chatbot.
    Streams state transitions, tool execution events, visual medicine cards, and tokens.
    Supports authenticated users and guest visitors.
    """
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    user_role = payload.get("role", UserRole.USER.value) if payload else UserRole.USER.value

    generator = service.stream_chat_turn(
        req=req,
        user_id=user_id,
        user_role=user_role,
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/sessions", response_model=APIResponse[List[ChatSessionResponse]])
async def list_sessions(
    session_type: Optional[SessionType] = Query(None),
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """Lists all active chat sessions for the authenticated user."""
    user_id = payload.get("sub") if payload else None
    if not user_id:
        return APIResponse(success=True, message="No active user session", data=[])
    sessions = await service.repo.list_user_sessions(user_id=user_id, session_type=session_type)
    return APIResponse(success=True, message="Chat sessions retrieved", data=sessions)

@router.post("/sessions", response_model=APIResponse[ChatSessionResponse], status_code=status.HTTP_201_CREATED)
async def create_session(
    req: ChatSessionCreate,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """Creates a new empty chat session."""
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    role = payload.get("role", UserRole.USER.value) if payload else UserRole.USER.value
    stype = SessionType.ADMIN if role in ["ADMIN", "DEVELOPER"] else req.session_type
    session = await service.repo.create_session(user_id=user_id, session_type=stype, title=req.title or "New Chat")
    return APIResponse(success=True, message="Session created", data=session)

@router.get("/sessions/{session_id}/messages", response_model=APIResponse[List[ChatMessageResponse]])
async def get_session_messages(
    session_id: str,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """Retrieves chronological messages in a session."""
    msgs = await service.repo.get_session_messages(session_id=session_id)
    return APIResponse(success=True, message="Session messages retrieved", data=msgs)

@router.delete("/sessions/{session_id}", response_model=APIResponse[dict])
async def archive_session(
    session_id: str,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """Archives (deletes) a chat session."""
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    success = await service.repo.archive_session(session_id=session_id, user_id=user_id)
    return APIResponse(success=success, message="Session archived", data={"deleted": success})
