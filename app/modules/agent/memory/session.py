from typing import List, Dict, Any
from app.modules.agent.memory.repository import AgentMemoryRepository

class SessionMemoryManager:
    """Manages context assembly and sliding window message buffers for LLM inference."""

    def __init__(self, repo: AgentMemoryRepository):
        self.repo = repo

    async def get_recent_messages_for_llm(self, session_id: str, window_size: int = 14) -> List[Dict[str, Any]]:
        raw_msgs = await self.repo.get_session_messages(session_id, limit=window_size)
        formatted = []
        for m in raw_msgs:
            role = m.get("role", "user")
            content = m.get("content", "")
            formatted_msg: Dict[str, Any] = {"role": role, "content": content}
            if m.get("tool_calls"):
                formatted_msg["tool_calls"] = m["tool_calls"]
            formatted.append(formatted_msg)
        return formatted

    def generate_initial_title(self, first_user_prompt: str) -> str:
        clean = first_user_prompt.strip().replace("\n", " ")
        if len(clean) > 40:
            return clean[:37] + "..."
        return clean or "New Conversation"
