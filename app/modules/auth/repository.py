from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

class AuthRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.users.find_one({"id": user_id})

    async def get_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        return await self.db.users.find_one({"phone": phone})

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.db.users.find_one({"email": email.lower()})

    async def get_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        return await self.db.users.find_one({
            "$or": [
                {"phone": identifier},
                {"email": identifier.lower()}
            ]
        })

    async def create_user(self, user_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in user_doc:
            user_doc["id"] = str(uuid.uuid4())
        if "created_at" not in user_doc:
            user_doc["created_at"] = datetime.now(timezone.utc)
        user_doc["updated_at"] = datetime.now(timezone.utc)
        await self.db.users.insert_one(user_doc)
        return user_doc

    async def update_password(self, user_id: str, hashed_password: str) -> bool:
        res = await self.db.users.update_one(
            {"id": user_id},
            {"$set": {"hashed_password": hashed_password, "updated_at": datetime.now(timezone.utc)}}
        )
        return res.modified_count > 0

    async def add_revoked_token(self, token: str, user_id: str, expires_at: datetime) -> None:
        await self.db.revoked_tokens.insert_one({
            "token": token,
            "user_id": user_id,
            "revoked_at": datetime.now(timezone.utc),
            "expires_at": expires_at
        })

    async def is_token_revoked(self, token: str) -> bool:
        doc = await self.db.revoked_tokens.find_one({"token": token})
        return doc is not None

