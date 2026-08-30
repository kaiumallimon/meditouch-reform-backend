from typing import Optional, Dict, Any, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re
from app.modules.pharmacy.schemas import (
    MedicineFilterParams,
    CrawlerSettingsModel
)

class PharmacyRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, medicine_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.medicines.find_one({"id": medicine_id})

    async def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return await self.db.medicines.find_one({"slug": slug})

    async def find_by_id_or_slug(self, identifier: str) -> Optional[Dict[str, Any]]:
        return await self.db.medicines.find_one({"$or": [{"id": identifier}, {"slug": identifier}]})

    async def get_detail_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return await self.db.medicine_details.find_one({"slug": slug})

    async def search_medicines(
        self,
        filters: MedicineFilterParams,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        query: Dict[str, Any] = {"is_active": True}

        if filters.search:
            search_regex = {"$regex": re.escape(filters.search.strip()), "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"medicine_name": search_regex},
                {"brand": search_regex},
                {"generic_name": search_regex},
                {"manufacturer": search_regex},
                {"manufacturer_name": search_regex},
                {"category_name": search_regex},
                {"slug": search_regex}
            ]

        if filters.generic_name:
            query["generic_name"] = {"$regex": f"^{re.escape(filters.generic_name)}$", "$options": "i"}

        if filters.category_slug:
            query["category_slug"] = filters.category_slug
        elif filters.category_name:
            query["category_name"] = {"$regex": f"^{re.escape(filters.category_name)}$", "$options": "i"}
        elif filters.category:
            cat_val = filters.category.value if hasattr(filters.category, "value") else str(filters.category)
            query["$or"] = [
                {"category": cat_val.upper()},
                {"category_name": {"$regex": f"^{re.escape(cat_val)}$", "$options": "i"}},
                {"category_slug": cat_val.lower()}
            ]

        if filters.requires_prescription is not None:
            query["$or"] = [
                {"rx_required": filters.requires_prescription},
                {"requires_prescription": filters.requires_prescription}
            ]

        if filters.in_stock_only is True:
            query["in_stock"] = True

        if filters.min_price is not None or filters.max_price is not None:
            price_query = {}
            if filters.min_price is not None:
                price_query["$gte"] = filters.min_price
            if filters.max_price is not None:
                price_query["$lte"] = filters.max_price
            query["unit_price"] = price_query

        if filters.manufacturer:
            m_regex = {"$regex": re.escape(filters.manufacturer), "$options": "i"}
            query["$or"] = [{"manufacturer": m_regex}, {"manufacturer_name": m_regex}]

        # Dynamic Server-side Sorting
        sort_criteria = [("medicine_name", 1), ("brand", 1)]
        if filters.sort_by == "name_desc":
            sort_criteria = [("medicine_name", -1), ("brand", -1)]
        elif filters.sort_by == "price_asc":
            sort_criteria = [("unit_price", 1), ("medicine_name", 1)]
        elif filters.sort_by == "price_desc":
            sort_criteria = [("unit_price", -1), ("medicine_name", 1)]
        elif filters.sort_by == "created_desc":
            sort_criteria = [("created_at", -1)]
        elif filters.sort_by == "created_asc":
            sort_criteria = [("created_at", 1)]
        elif filters.sort_by == "manufacturer_asc":
            sort_criteria = [("manufacturer_name", 1), ("medicine_name", 1)]
        elif filters.sort_by == "manufacturer_desc":
            sort_criteria = [("manufacturer_name", -1), ("medicine_name", 1)]

        total = await self.db.medicines.count_documents(query)
        cursor = self.db.medicines.find(query).skip(skip).limit(limit).sort(sort_criteria)
        items = await cursor.to_list(length=limit)
        return items, total

    async def create_medicine(self, medicine_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in medicine_doc:
            medicine_doc["id"] = str(uuid.uuid4())
        brand = medicine_doc.get("brand") or medicine_doc.get("medicine_name", "")
        strength = medicine_doc.get("strength", "")
        medicine_doc["name"] = f"{brand} {strength}".strip()
        medicine_doc["medicine_name"] = brand
        medicine_doc["brand"] = brand
        if "slug" not in medicine_doc:
            clean_slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{brand}-{strength}").strip("-").lower()
            medicine_doc["slug"] = clean_slug
        medicine_doc["manufacturer_name"] = medicine_doc.get("manufacturer") or "Square Pharmaceuticals Ltd."
        medicine_doc["unit_prices"] = medicine_doc.get("unit_prices") or []
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

    async def delete_medicine(self, medicine_id_or_slug: str) -> bool:
        res = await self.db.medicines.delete_one({
            "$or": [{"id": medicine_id_or_slug}, {"slug": medicine_id_or_slug}]
        })
        return res.deleted_count > 0

    async def delete_medicines_bulk(self, ids_or_slugs: List[str]) -> int:
        res = await self.db.medicines.delete_many({
            "$or": [
                {"id": {"$in": ids_or_slugs}},
                {"slug": {"$in": ids_or_slugs}}
            ]
        })
        return res.deleted_count

    async def get_categories_summary(self) -> List[Dict[str, Any]]:
        pipeline = [
            {"$match": {"is_active": True}},
            {
                "$group": {
                    "_id": {
                        "$ifNull": ["$category_name", "$category"]
                    },
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"count": -1}}
        ]
        res = await self.db.medicines.aggregate(pipeline).to_list(length=50)
        return [{"category": str(r["_id"]), "count": r["count"]} for r in res if r.get("_id")]

    async def get_pharmacy_stats(self) -> Dict[str, Any]:
        total_medicines = await self.db.medicines.count_documents({"is_active": True})
        in_stock_medicines = await self.db.medicines.count_documents({"is_active": True, "in_stock": True})
        
        cats = await self.db.medicines.distinct("category_name", {"is_active": True})
        total_categories = len(cats) if cats else len(await self.db.medicines.distinct("category", {"is_active": True}))

        manufs = await self.db.medicines.distinct("manufacturer_name", {"is_active": True})
        total_manufacturers = len(manufs) if manufs else len(await self.db.medicines.distinct("manufacturer", {"is_active": True}))

        latest_job = await self.db.crawler_jobs.find_one(sort=[("started_at", -1)])
        last_crawled_at = latest_job.get("started_at") if latest_job else None
        crawler_status = latest_job.get("status") if latest_job else "IDLE"

        return {
            "total_medicines": total_medicines,
            "in_stock_medicines": in_stock_medicines,
            "total_categories": total_categories,
            "total_manufacturers": total_manufacturers,
            "last_crawled_at": last_crawled_at,
            "crawler_status": crawler_status
        }

    # Crawler Settings DB Methods
    async def get_crawler_settings(self) -> CrawlerSettingsModel:
        doc = await self.db.crawler_settings.find_one({"id": "default_settings"})
        if not doc:
            defaults = CrawlerSettingsModel()
            doc_dict = defaults.model_dump()
            doc_dict["id"] = "default_settings"
            doc_dict["updated_at"] = datetime.now(timezone.utc)
            await self.db.crawler_settings.insert_one(doc_dict)
            return defaults
        return CrawlerSettingsModel(**doc)

    async def update_crawler_settings(self, updates: Dict[str, Any]) -> CrawlerSettingsModel:
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = await self.db.crawler_settings.find_one_and_update(
            {"id": "default_settings"},
            {"$set": updates},
            upsert=True,
            return_document=True
        )
        return CrawlerSettingsModel(**updated)

    async def get_crawler_job_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self.db.crawler_jobs.find().sort("started_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
