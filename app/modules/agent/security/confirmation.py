import uuid
import time
from typing import Dict, Any, Optional
from app.modules.agent.schemas.tools import ConfirmationPayload

class ConfirmationManager:
    """
    In-memory / Cache manager for 2-step confirmation of destructive admin operations.
    Tokens expire after 5 minutes (TTL = 300s).
    """

    def __init__(self, ttl_seconds: int = 300):
        self._pending: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds

    def create_pending_confirmation(
        self,
        session_id: str,
        action: str,
        target_type: str,
        target_id: str,
        target_name: Optional[str],
        summary: str,
        command_data: Dict[str, Any],
    ) -> str:
        token = str(uuid.uuid4())
        self._pending[token] = {
            "token": token,
            "session_id": session_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "target_name": target_name,
            "summary": summary,
            "command_data": command_data,
            "created_at": time.time(),
            "expires_at": time.time() + self.ttl,
        }
        return token

    def get_pending_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        self._cleanup_expired()
        for token, data in self._pending.items():
            if data["session_id"] == session_id:
                return data
        return None

    def validate_and_consume(self, token: str, session_id: str) -> Optional[Dict[str, Any]]:
        self._cleanup_expired()
        item = self._pending.get(token)
        if not item:
            return None
        if item["session_id"] != session_id:
            return None
        if time.time() > item["expires_at"]:
            del self._pending[token]
            return None

        # Consumed successfully
        del self._pending[token]
        return item

    def cancel_by_session(self, session_id: str):
        tokens_to_delete = [
            token for token, data in self._pending.items()
            if data["session_id"] == session_id
        ]
        for t in tokens_to_delete:
            del self._pending[t]

    def _cleanup_expired(self):
        now = time.time()
        expired = [t for t, data in self._pending.items() if now > data["expires_at"]]
        for t in expired:
            del self._pending[t]

# Global Singleton instance
confirmation_manager = ConfirmationManager()
