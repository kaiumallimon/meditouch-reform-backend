from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

class UserManagementRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.users.find_one({"id": user_id})

    async def update_profile(self, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates["updated_at"] = datetime.now(timezone.utc)
        await self.db.users.update_one({"id": user_id}, {"$set": updates})
        return await self.get_by_id(user_id)

    async def add_address(self, user_id: str, address: Dict[str, Any]) -> List[Dict[str, Any]]:
        if "id" not in address or not address["id"]:
            address["id"] = str(uuid.uuid4())
        
        # If this is set as default, reset other addresses
        if address.get("is_default", False):
            await self.db.users.update_one(
                {"id": user_id},
                {"$set": {"addresses.$[].is_default": False}}
            )

        await self.db.users.update_one(
            {"id": user_id},
            {"$push": {"addresses": address}, "$set": {"updated_at": datetime.now(timezone.utc)}}
        )
        user = await self.get_by_id(user_id)
        return user.get("addresses", [])

