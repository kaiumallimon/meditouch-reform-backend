from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re
from app.modules.pharmacy.schemas import MedicineFilterParams

class PharmacyRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, medicine_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.medicines.find_one({"id": medicine_id})

    async def search_medicines(
        self,
        filters: MedicineFilterParams,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {"is_active": True}

        if filters.search:
            search_regex = {"$regex": re.escape(filters.search), "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"brand": search_regex},
                {"generic_name": search_regex},
                {"manufacturer": search_regex}
            ]

        if filters.generic_name:
            query["generic_name"] = {"$regex": f"^{re.escape(filters.generic_name)}$", "$options": "i"}

        if filters.category:
            query["category"] = filters.category.value if hasattr(filters.category, "value") else filters.category

        if filters.requires_prescription is not None:
            query["requires_prescription"] = filters.requires_prescription

        if filters.in_stock_only is True:
            query["in_stock"] = True
            query["stock_count"] = {"$gt": 0}

        if filters.min_price is not None or filters.max_price is not None:
            price_query = {}
            if filters.min_price is not None:
                price_query["$gte"] = filters.min_price
            if filters.max_price is not None:
                price_query["$lte"] = filters.max_price
            query["unit_price"] = price_query

        if filters.manufacturer:
            query["manufacturer"] = {"$regex": re.escape(filters.manufacturer), "$options": "i"}

        total = await self.db.medicines.count_documents(query)
        cursor = self.db.medicines.find(query).skip(skip).limit(limit).sort("brand", 1)
        items = await cursor.to_list(length=limit)
        return items, total

    async def create_medicine(self, medicine_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in medicine_doc:
            medicine_doc["id"] = str(uuid.uuid4())
        medicine_doc["name"] = f"{medicine_doc.get('brand', '')} {medicine_doc.get('strength', '')}".strip()
        medicine_doc["in_stock"] = medicine_doc.get("stock_count", 0) > 0
        medicine_doc["is_active"] = True
        medicine_doc["created_at"] = datetime.now(timezone.utc)
        medicine_doc["updated_at"] = datetime.now(timezone.utc)
        await self.db.medicines.insert_one(medicine_doc)
        return medicine_doc

    async def update_medicine(self, medicine_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates["updated_at"] = datetime.now(timezone.utc)
        if "stock_count" in updates:
            updates["in_stock"] = updates["stock_count"] > 0
        return await self.db.medicines.find_one_and_update(
            {"id": medicine_id},
            {"$set": updates},
            return_document=True
        )

    async def get_categories_summary(self) -> List[Dict[str, Any]]:
        pipeline = [
            {"$match": {"is_active": True}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        res = await self.db.medicines.aggregate(pipeline).to_list(length=50)
        return [{"category": r["_id"], "count": r["count"]} for r in res if r.get("_id")]

