from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum

class SessionType(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"

class AgentState(str, Enum):
    RECEIVED = "RECEIVED"
    AUTHENTICATING = "AUTHENTICATING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    EVALUATING = "EVALUATING"
    FINALIZING = "FINALIZING"
    STREAMING = "STREAMING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"

class StreamEventType(str, Enum):
    SESSION = "session"
    STATE = "state"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MEDICINE_CARDS = "medicine_cards"
    TOKEN = "token"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_RESULT = "confirmation_result"
    CLARIFICATION_REQUIRED = "clarification_required"
    ERROR = "error"
    DONE = "done"

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    confirmation_token: Optional[str] = None
    confirmed: Optional[bool] = None

class ChatSessionCreate(BaseModel):
    title: Optional[str] = "New Conversation"
    session_type: SessionType = SessionType.USER

class ChatSessionResponse(BaseModel):
    id: str
    user_id: str
    session_type: SessionType
    title: str
    created_at: datetime
    updated_at: datetime
    is_archived: bool = False

class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    user_id: str
    role: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

class StreamEvent(BaseModel):
    event: StreamEventType
    data: Dict[str, Any]
