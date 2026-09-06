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
        search: Optional[str] = None,
        sort_by: Optional[str] = "created_desc",
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status.value if isinstance(status, OrderStatus) else status

        if search and search.strip():
            s = search.strip()
            query["$or"] = [
                {"order_number": {"$regex": s, "$options": "i"}},
                {"user_name": {"$regex": s, "$options": "i"}},
                {"user_phone": {"$regex": s, "$options": "i"}},
                {"delivery_address.recipient_name": {"$regex": s, "$options": "i"}},
                {"delivery_address.recipient_phone": {"$regex": s, "$options": "i"}},
                {"delivery_address.street_address": {"$regex": s, "$options": "i"}},
                {"items.name": {"$regex": s, "$options": "i"}},
                {"items.brand": {"$regex": s, "$options": "i"}},
            ]

        sort_field = "created_at"
        sort_dir = -1
        if sort_by == "created_asc":
            sort_field, sort_dir = "created_at", 1
        elif sort_by == "amount_desc":
            sort_field, sort_dir = "total_amount", -1
        elif sort_by == "amount_asc":
            sort_field, sort_dir = "total_amount", 1
        elif sort_by == "status_asc":
            sort_field, sort_dir = "status", 1
        elif sort_by == "customer_asc":
            sort_field, sort_dir = "user_name", 1

        total = await self.db.orders.count_documents(query)
        cursor = self.db.orders.find(query).sort(sort_field, sort_dir).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_order_stats(self) -> Dict[str, Any]:
        pipeline = [
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "total_amount": {"$sum": "$total_amount"}
                }
            }
        ]
        results = await self.db.orders.aggregate(pipeline).to_list(length=100)

        counts = {
            "CONFIRMED": 0,
            "PROCESSING": 0,
            "SHIPPED": 0,
            "DELIVERED": 0,
            "CANCELLED": 0,
        }
        total_orders = 0
        total_revenue = 0.0

        for r in results:
            st = str(r.get("_id"))
            c = int(r.get("count", 0))
            amt = float(r.get("total_amount", 0.0))
            if st in counts:
                counts[st] = c
            total_orders += c
            if st != "CANCELLED":
                total_revenue += amt

        return {
            "total_orders": total_orders,
            "confirmed_count": counts["CONFIRMED"],
            "processing_count": counts["PROCESSING"],
            "shipped_count": counts["SHIPPED"],
            "delivered_count": counts["DELIVERED"],
            "cancelled_count": counts["CANCELLED"],
            "total_revenue": round(total_revenue, 2)
        }


