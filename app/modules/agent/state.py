from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.modules.agent.schemas.chat import AgentState, SessionType

class AgentExecutionState(BaseModel):
    session_id: str
    user_id: str
    user_role: str
    session_type: SessionType
    current_state: AgentState = AgentState.RECEIVED
    step_count: int = 0
    tool_call_count: int = 0
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    messages: List[Dict[str, Any]] = []
    pending_tool_calls: List[Dict[str, Any]] = []
    completed_tool_results: List[Dict[str, Any]] = []
    accumulated_content: str = ""
    error: Optional[str] = None

    def transition(self, next_state: AgentState):
        self.current_state = next_state

    def increment_step(self):
        self.step_count += 1

    def increment_tool_call(self):
        self.tool_call_count += 1
