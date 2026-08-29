from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.schemas.chat import SessionType

class AgentMemoryRepository:
    """MongoDB repository for `chat_sessions` and `chat_messages` collections."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_session(self, user_id: str, session_type: SessionType, title: str = "New Conversation") -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        doc = {
            "id": session_id,
            "user_id": user_id,
            "session_type": session_type.value,
            "title": title,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "is_archived": False,
        }
        await self.db.chat_sessions.insert_one(doc)
        return doc

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.chat_sessions.find_one({"id": session_id, "is_archived": {"$ne": True}})

    async def list_user_sessions(self, user_id: str, session_type: Optional[SessionType] = None) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": user_id, "is_archived": {"$ne": True}}
        if session_type:
            query["session_type"] = session_type.value
        cursor = self.db.chat_sessions.find(query).sort("updated_at", -1).limit(50)
        return await cursor.to_list(length=50)

    async def update_session_title(self, session_id: str, title: str):
        now = datetime.now(timezone.utc)
        await self.db.chat_sessions.update_one(
            {"id": session_id},
            {"$set": {"title": title, "updated_at": now.isoformat()}}
        )

    async def archive_session(self, session_id: str, user_id: str) -> bool:
        res = await self.db.chat_sessions.update_one(
            {"id": session_id, "user_id": user_id},
            {"$set": {"is_archived": True, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return res.modified_count > 0

    async def add_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        doc = {
            "id": msg_id,
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "tool_results_metadata": tool_results_metadata,
            "created_at": now.isoformat(),
        }
        await self.db.chat_messages.insert_one(doc)
        # Update session touch timestamp
        await self.db.chat_sessions.update_one({"id": session_id}, {"$set": {"updated_at": now.isoformat()}})
        return doc

    async def get_session_messages(self, session_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        cursor = self.db.chat_messages.find({"session_id": session_id}).sort("created_at", 1).limit(limit)
        return await cursor.to_list(length=limit)
