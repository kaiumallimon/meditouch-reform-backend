import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.logging import logger

DEFAULT_ACTION_TTL_SECONDS = 300  # 5 minutes

class AgentPendingActionRepository:
    """
    MongoDB-persisted repository for 2-step administrative action confirmations.
    Replaces ephemeral in-memory storage for 100% Vercel / serverless compatibility.
    Guarantees atomic, single-use, actor-bound, and session-bound execution.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.agent_pending_actions

    async def create_pending_action(
        self,
        actor_id: str,
        actor_role: str,
        session_id: str,
        action: str,
        target_type: str,
        target_id: str,
        target_name: Optional[str],
        summary: str,
        command_data: Dict[str, Any],
        ttl_seconds: int = DEFAULT_ACTION_TTL_SECONDS,
    ) -> str:
        token = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        doc = {
            "id": token,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "session_id": session_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "target_name": target_name,
            "summary": summary,
            "command_data": command_data,
            "status": "PENDING",
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "confirmed_at": None,
            "executed_at": None,
        }

        await self.collection.insert_one(doc)
        logger.info(f"Agent Pending Action created: [{token}] {action} on {target_type}:{target_id} by {actor_id}")
        return token

    async def get_pending_action(self, token: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"id": token})

    async def validate_and_consume(
        self,
        token: str,
        actor_id: str,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically validates and transitions the pending action to 'EXECUTING'.
        Enforces:
        1. Token existence & matching id
        2. Actor binding (must match actor_id)
        3. Session binding (must match session_id)
        4. Expiration check (expires_at > now)
        5. Single-use state transition (status == 'PENDING')
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Atomic find-and-update to prevent race conditions or replay
        doc = await self.collection.find_one_and_update(
            {
                "id": token,
                "actor_id": actor_id,
                "session_id": session_id,
                "status": "PENDING",
                "expires_at": {"$gt": now_iso},
            },
            {
                "$set": {
                    "status": "EXECUTING",
                    "confirmed_at": now_iso,
                }
            }
        )

        if not doc:
            logger.warning(f"Failed to consume pending action token: {token} (actor: {actor_id}, session: {session_id})")
            return None

        return doc

    async def mark_completed(self, token: str, result_metadata: Optional[Dict[str, Any]] = None):
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one(
            {"id": token},
            {
                "$set": {
                    "status": "COMPLETED",
                    "executed_at": now_iso,
                    "result_metadata": result_metadata or {},
                }
            }
        )

    async def mark_failed(self, token: str, error_message: str):
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one(
            {"id": token},
            {
                "$set": {
                    "status": "FAILED",
                    "executed_at": now_iso,
                    "error_message": error_message,
                }
            }
        )

    async def cancel_pending_action(self, token: str, actor_id: str) -> bool:
        res = await self.collection.update_one(
            {"id": token, "actor_id": actor_id, "status": "PENDING"},
            {"$set": {"status": "CANCELLED"}}
        )
        return res.modified_count > 0

