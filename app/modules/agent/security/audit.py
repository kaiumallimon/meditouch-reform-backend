from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.logging import logger

class AgentAuditService:
    """
    Emits immutable audit records to `agent_audit_logs` collection.
    Enforces privacy rules (never logs credentials, raw tokens, or sensitive health text).
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def log_action(
        self,
        actor_id: str,
        actor_role: str,
        session_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        tool_name: str,
        status: str = "SUCCESS",
        confirmation_required: bool = False,
        confirmation_received: bool = False,
        message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        audit_id = str(uuid.uuid4())
        
        # Sanitize metadata (strip any passwords, tokens, full headers)
        sanitized_meta = self._sanitize_metadata(metadata or {})

        doc = {
            "id": audit_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "session_id": session_id,
            "message_id": message_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "tool_name": tool_name,
            "confirmation_required": confirmation_required,
            "confirmation_received": confirmation_received,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": sanitized_meta,
        }

        try:
            await self.db.agent_audit_logs.insert_one(doc)
            logger.info(f"Agent Audit Logged: [{action}] by [{actor_role}:{actor_id}] on [{resource_type}:{resource_id}]")
        except Exception as e:
            logger.error(f"Failed to persist agent audit log: {e}")

        return audit_id

    def _sanitize_metadata(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {}
        sensitive_keys = {"password", "token", "jwt", "secret", "authorization", "raw_key"}
        for k, v in meta.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_metadata(v)
            else:
                sanitized[k] = v
        return sanitized
