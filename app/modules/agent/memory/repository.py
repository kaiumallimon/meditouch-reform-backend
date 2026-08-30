import re
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.schemas.chat import SessionType
from app.core.logging import logger


class AgentMemoryRepository:
    """MongoDB repository for `chat_sessions` and `chat_messages` collections."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_session(
        self,
        user_id: str,
        session_type: SessionType,
        title: str = "Conversation",
        initial_message_count: int = 0,
    ) -> Dict[str, Any]:
        """Creates a new session document in MongoDB."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        doc = {
            "id": session_id,
            "user_id": user_id,
            "session_type": session_type.value,
            "title": title,
            "message_count": initial_message_count,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "last_message_at": now.isoformat(),
            "is_archived": False,
        }
        await self.db.chat_sessions.insert_one(doc)
        return doc

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single non-archived session by ID."""
        return await self.db.chat_sessions.find_one({"id": session_id, "is_archived": {"$ne": True}})

    async def list_user_sessions(
        self,
        user_id: str,
        session_type: Optional[SessionType] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Lists chat sessions owned by the caller.

        CRITICAL INVARIANT:
        Only returns sessions with actual user activity (message_count > 0).
        Zero-message empty draft sessions are never returned in history.
        """
        query: Dict[str, Any] = {
            "user_id": user_id,
            "is_archived": {"$ne": True},
            "message_count": {"$gt": 0},
        }
        if session_type:
            query["session_type"] = session_type.value

        cursor = self.db.chat_sessions.find(query).sort("last_message_at", -1).limit(limit)
        results = await cursor.to_list(length=limit)

        # Fallback for legacy documents that might not have message_count set yet:
        # If no results found with message_count > 0, check for unmigrated sessions with messages
        if not results:
            fallback_query: Dict[str, Any] = {
                "user_id": user_id,
                "is_archived": {"$ne": True},
                "message_count": {"$exists": False},
            }
            if session_type:
                fallback_query["session_type"] = session_type.value
            unmigrated = await self.db.chat_sessions.find(fallback_query).sort("updated_at", -1).limit(limit).to_list(length=limit)
            for s in unmigrated:
                # Count actual messages in chat_messages
                c = await self.db.chat_messages.count_documents({"session_id": s["id"]})
                if c > 0:
                    await self.db.chat_sessions.update_one({"id": s["id"]}, {"$set": {"message_count": c}})
                    s["message_count"] = c
                    results.append(s)

        return results

    async def update_session_title(self, session_id: str, title: str) -> None:
        """Updates session title and touch timestamp."""
        now = datetime.now(timezone.utc)
        await self.db.chat_sessions.update_one(
            {"id": session_id},
            {"$set": {"title": title, "updated_at": now.isoformat()}}
        )

    async def archive_session(self, session_id: str, user_id: str) -> bool:
        """Soft-deletes (archives) a chat session."""
        now = datetime.now(timezone.utc)
        res = await self.db.chat_sessions.update_one(
            {"id": session_id, "user_id": user_id},
            {"$set": {"is_archived": True, "updated_at": now.isoformat()}}
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
        """
        Inserts a message and atomically increments the parent session's message_count
        and touches last_message_at.
        """
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

        # Atomically increment session message_count and touch last_message_at
        await self.db.chat_sessions.update_one(
            {"id": session_id},
            {
                "$set": {
                    "updated_at": now.isoformat(),
                    "last_message_at": now.isoformat(),
                },
                "$inc": {"message_count": 1},
            },
        )
        return doc

    async def get_session_messages(self, session_id: str, limit: int = 40) -> List[Dict[str, Any]]:
        """Retrieves chronological messages for a given session."""
        cursor = self.db.chat_messages.find({"session_id": session_id}).sort("created_at", 1).limit(limit)
        return await cursor.to_list(length=limit)

    async def cleanup_legacy_empty_sessions(self) -> Dict[str, int]:
        """
        Safe maintenance & migration routine:
        1. Archives legacy 0-message sessions created by previous empty '+ New' clicks.
        2. Sets accurate `message_count` on existing valid sessions.
        3. For sessions with messages that still have placeholder titles ('New Conversation', etc.),
           regenerates a meaningful title from their first user message.
        """
        archived_count = 0
        repaired_titles = 0
        updated_counts = 0

        try:
            # Iterate through active sessions
            cursor = self.db.chat_sessions.find({"is_archived": {"$ne": True}})
            sessions = await cursor.to_list(length=1000)

            for s in sessions:
                s_id = s["id"]
                # Count actual messages
                msg_count = await self.db.chat_messages.count_documents({"session_id": s_id})

                if msg_count == 0:
                    # Archive empty session
                    await self.db.chat_sessions.update_one(
                        {"id": s_id},
                        {"$set": {"is_archived": True, "message_count": 0, "archived_reason": "cleanup_empty_session"}}
                    )
                    archived_count += 1
                else:
                    updates: Dict[str, Any] = {}
                    if s.get("message_count") != msg_count:
                        updates["message_count"] = msg_count
                        updated_counts += 1

                    # Check placeholder title
                    curr_title = s.get("title", "")
                    if curr_title in ["New Conversation", "New Chat", "New Admin Session", "New Conversation...", "Conversation", ""]:
                        # Find first user message to derive a real title
                        first_user_msg = await self.db.chat_messages.find_one(
                            {"session_id": s_id, "role": "user"},
                            sort=[("created_at", 1)]
                        )
                        if first_user_msg and first_user_msg.get("content"):
                            prompt = first_user_msg["content"].strip().replace("\n", " ")
                            prompt = re.sub(r"^[#*`\-–—]+\s*", "", prompt)
                            prompt = re.sub(r"\s+", " ", prompt).strip()
                            new_title = prompt[:33].rstrip() + "..." if len(prompt) > 36 else prompt
                            updates["title"] = new_title or "Conversation"
                            repaired_titles += 1

                    if updates:
                        await self.db.chat_sessions.update_one({"id": s_id}, {"$set": updates})

            logger.info(
                f"[SessionCleanup] Completed: archived {archived_count} empty sessions, "
                f"repaired {repaired_titles} titles, synced {updated_counts} message counts."
            )
        except Exception as e:
            logger.warning(f"[SessionCleanup] Error during legacy session cleanup: {e}")

        return {
            "archived_empty_sessions": archived_count,
            "repaired_titles": repaired_titles,
            "synced_message_counts": updated_counts,
        }
