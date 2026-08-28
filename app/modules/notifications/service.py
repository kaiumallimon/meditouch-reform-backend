from typing import List, Optional, Dict, Any
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationResponse
from app.common.enums import NotificationType
from app.core.logging import logger

class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self.repo = repo

    async def send_notification(
        self,
        user_id: str,
        notif_type: NotificationType,
        title: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> NotificationResponse:
        doc = {
            "user_id": user_id,
            "type": notif_type.value if isinstance(notif_type, NotificationType) else notif_type,
            "title": title,
            "message": message,
            "payload": payload or {}
        }
        saved = await self.repo.create(doc)
        logger.info(f"NOTIFICATION_SENT: to user={user_id} type={notif_type} title={title}")
        return NotificationResponse(**saved)

    async def get_user_notifications(self, user_id: str, limit: int = 50) -> List[NotificationResponse]:
        items = await self.repo.get_user_notifications(user_id, limit=limit)
        return [NotificationResponse(**item) for item in items]

    async def mark_notification_read(self, notification_id: str, user_id: str) -> bool:
        return await self.repo.mark_as_read(notification_id, user_id)

    async def mark_all_read(self, user_id: str) -> int:
        return await self.repo.mark_all_as_read(user_id)

