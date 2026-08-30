from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.core.security import get_optional_user_payload, get_current_user_payload
from app.core.exceptions import ForbiddenException, NotFoundException, UnauthorizedException
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

# -----------------------------------------------------------------------------
# User / Patient / General Chat Router (/api/v1/chat)
# -----------------------------------------------------------------------------
router = APIRouter(prefix="/chat", tags=["Agentic AI Assistant"])

def get_agent_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> AgentChatService:
    return AgentChatService(db)

def require_admin_role(payload: dict = Depends(get_current_user_payload)) -> dict:
    role = payload.get("role")
    if role not in [UserRole.ADMIN.value, UserRole.DEVELOPER.value]:
        raise ForbiddenException("Access restricted to platform administrators only.")
    return payload

@router.post("/stream")
async def stream_chat(
    req: ChatRequest,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """
    Real-time Server-Sent Events (SSE) streaming endpoint for client apps (Flutter & Web).
    Streams state transitions, clinical triage assessment, visual medicine cards, and tokens.
    """
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    user_role = payload.get("role", UserRole.USER.value) if payload else UserRole.USER.value

    generator = service.stream_chat_turn(
        req=req,
        user_id=user_id,
        user_role=user_role,
        explicit_session_type=SessionType.USER,
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
    """Lists chat sessions owned by the caller."""
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
    """Creates a new empty chat session for the authenticated user."""
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    session = await service.repo.create_session(
        user_id=user_id,
        session_type=SessionType.USER,
        title=req.title or "New Chat"
    )
    return APIResponse(success=True, message="Session created", data=session)

@router.get("/sessions/{session_id}/messages", response_model=APIResponse[List[ChatMessageResponse]])
async def get_session_messages(
    session_id: str,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """Retrieves messages in a session with ownership verification."""
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    session = await service.repo.get_session(session_id)
    if not session:
        raise NotFoundException(f"Chat session '{session_id}' not found.")
    if session.get("user_id") != user_id:
        raise ForbiddenException("Access denied: You do not own this chat session.")

    msgs = await service.repo.get_session_messages(session_id=session_id)
    return APIResponse(success=True, message="Session messages retrieved", data=msgs)

@router.delete("/sessions/{session_id}", response_model=APIResponse[dict])
async def archive_session(
    session_id: str,
    payload: Optional[dict] = Depends(get_optional_user_payload),
    service: AgentChatService = Depends(get_agent_service),
):
    """Archives (deletes) a chat session with ownership verification."""
    user_id = payload.get("sub", "guest_user") if payload else "guest_user"
    session = await service.repo.get_session(session_id)
    if not session:
        raise NotFoundException(f"Chat session '{session_id}' not found.")
    if session.get("user_id") != user_id:
        raise ForbiddenException("Access denied: You do not own this chat session.")

    success = await service.repo.archive_session(session_id=session_id, user_id=user_id)
    return APIResponse(success=success, message="Session archived", data={"deleted": success})


# -----------------------------------------------------------------------------
# Dedicated Admin Chat Router (/api/v1/admin/chat)
# -----------------------------------------------------------------------------
admin_chat_router = APIRouter(prefix="/admin/chat", tags=["Admin Agentic Assistant"])

@admin_chat_router.post("/stream")
async def stream_admin_chat(
    req: ChatRequest,
    payload: dict = Depends(require_admin_role),
    service: AgentChatService = Depends(get_agent_service),
):
    """
    Dedicated admin SSE stream endpoint for administrative tasks with strict RBAC.
    """
    user_id = payload["sub"]
    user_role = payload.get("role", UserRole.ADMIN.value)

    generator = service.stream_chat_turn(
        req=req,
        user_id=user_id,
        user_role=user_role,
        explicit_session_type=SessionType.ADMIN,
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

@admin_chat_router.get("/sessions", response_model=APIResponse[List[ChatSessionResponse]])
async def list_admin_sessions(
    payload: dict = Depends(require_admin_role),
    service: AgentChatService = Depends(get_agent_service),
):
    """Lists all admin chat sessions for the authenticated administrator."""
    user_id = payload["sub"]
    sessions = await service.repo.list_user_sessions(user_id=user_id, session_type=SessionType.ADMIN)
    return APIResponse(success=True, message="Admin chat sessions retrieved", data=sessions)

@admin_chat_router.post("/sessions", response_model=APIResponse[ChatSessionResponse], status_code=status.HTTP_201_CREATED)
async def create_admin_session(
    req: ChatSessionCreate,
    payload: dict = Depends(require_admin_role),
    service: AgentChatService = Depends(get_agent_service),
):
    """Creates a new dedicated admin chat session."""
    user_id = payload["sub"]
    session = await service.repo.create_session(
        user_id=user_id,
        session_type=SessionType.ADMIN,
        title=req.title or "New Admin Session"
    )
    return APIResponse(success=True, message="Admin session created", data=session)

@admin_chat_router.get("/sessions/{session_id}/messages", response_model=APIResponse[List[ChatMessageResponse]])
async def get_admin_session_messages(
    session_id: str,
    payload: dict = Depends(require_admin_role),
    service: AgentChatService = Depends(get_agent_service),
):
    """Retrieves admin session messages with ownership verification."""
    user_id = payload["sub"]
    session = await service.repo.get_session(session_id)
    if not session:
        raise NotFoundException(f"Admin session '{session_id}' not found.")
    if session.get("user_id") != user_id:
        raise ForbiddenException("Access denied: You do not own this admin session.")

    msgs = await service.repo.get_session_messages(session_id=session_id)
    return APIResponse(success=True, message="Admin session messages retrieved", data=msgs)

@admin_chat_router.delete("/sessions/{session_id}", response_model=APIResponse[dict])
async def archive_admin_session(
    session_id: str,
    payload: dict = Depends(require_admin_role),
    service: AgentChatService = Depends(get_agent_service),
):
    """Archives an admin chat session with ownership verification."""
    user_id = payload["sub"]
    session = await service.repo.get_session(session_id)
    if not session:
        raise NotFoundException(f"Admin session '{session_id}' not found.")
    if session.get("user_id") != user_id:
        raise ForbiddenException("Access denied: You do not own this admin session.")

    success = await service.repo.archive_session(session_id=session_id, user_id=user_id)
    return APIResponse(success=success, message="Admin session archived", data={"deleted": success})
