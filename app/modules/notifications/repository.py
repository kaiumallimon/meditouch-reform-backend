from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

class NotificationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create(self, notif_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in notif_doc:
            notif_doc["id"] = str(uuid.uuid4())
        if "created_at" not in notif_doc:
            notif_doc["created_at"] = datetime.now(timezone.utc)
        notif_doc["is_read"] = False
        await self.db.notifications.insert_one(notif_doc)
        return notif_doc

    async def get_user_notifications(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.db.notifications.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        res = await self.db.notifications.update_one(
            {"id": notification_id, "user_id": user_id},
            {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc)}}
        )
        return res.modified_count > 0

    async def mark_all_as_read(self, user_id: str) -> int:
        res = await self.db.notifications.update_many(
            {"user_id": user_id, "is_read": False},
            {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc)}}
        )
        return res.modified_count

