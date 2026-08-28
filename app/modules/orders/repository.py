from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
from app.common.enums import OrderStatus

class OrderRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # 1. Cart Operations
    async def get_cart_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.carts.find_one({"user_id": user_id})

    async def save_cart(self, user_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        doc = {
            "user_id": user_id,
            "items": items,
            "updated_at": datetime.now(timezone.utc)
        }
        await self.db.carts.update_one(
            {"user_id": user_id},
            {"$set": doc},
            upsert=True
        )
        return doc

    async def clear_cart(self, user_id: str) -> None:
        await self.db.carts.delete_one({"user_id": user_id})

    # 2. Order Operations
    async def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.orders.find_one({"id": order_id})

    async def create_order(self, order_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in order_doc:
            order_doc["id"] = str(uuid.uuid4())
        if "created_at" not in order_doc:
            order_doc["created_at"] = datetime.now(timezone.utc)
        order_doc["updated_at"] = datetime.now(timezone.utc)
        await self.db.orders.insert_one(order_doc)
        return order_doc

    async def update_order_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        tracking_note: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        tracking_event = {
            "status": new_status.value if isinstance(new_status, OrderStatus) else new_status,
            "note": tracking_note or f"Order status changed to {new_status}",
            "timestamp": now
        }
        return await self.db.orders.find_one_and_update(
            {"id": order_id},
            {
                "$set": {
                    "status": new_status.value if isinstance(new_status, OrderStatus) else new_status,
                    "updated_at": now
                },
                "$push": {"tracking_history": tracking_event}
            },
            return_document=True
        )

    async def get_user_orders(
        self,
        user_id: str,
        status: Optional[OrderStatus] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {"user_id": user_id}
        if status:
            query["status"] = status.value if isinstance(status, OrderStatus) else status

        total = await self.db.orders.count_documents(query)
        cursor = self.db.orders.find(query).skip(skip).limit(limit).sort("created_at", -1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_all_orders(
        self,
        status: Optional[OrderStatus] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status.value if isinstance(status, OrderStatus) else status

        total = await self.db.orders.count_documents(query)
        cursor = self.db.orders.find(query).skip(skip).limit(limit).sort("created_at", -1)
        items = await cursor.to_list(length=limit)
        return items, total

