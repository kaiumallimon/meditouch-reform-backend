from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum

class ToolExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"

class ToolCallDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any]

class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    status: ToolExecutionStatus
    result: Any
    error_message: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_token: Optional[str] = None
    confirmation_prompt: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ConfirmationPayload(BaseModel):
    action: str
    target_type: str
    target_id: str
    target_name: Optional[str] = None
    summary: str
    command_data: Dict[str, Any]
