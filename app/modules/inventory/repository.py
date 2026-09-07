from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import re
import uuid

class InventoryRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_overview_metrics(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        soon_threshold = now + timedelta(days=60)

        # Pipeline for SKU metrics from medicines collection
        sku_pipeline = [
            {
                "$project": {
                    "stock_count": {"$ifNull": ["$stock_count", 0]},
                    "unit_price": {"$ifNull": ["$unit_price", 0.0]},
                    "min_stock_alert": {"$ifNull": ["$min_stock_alert", 10]},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_skus": {"$sum": 1},
                    "total_stock_units": {"$sum": "$stock_count"},
                    "total_valuation_bdt": {
                        "$sum": {"$multiply": ["$stock_count", "$unit_price"]}
                    },
                    "out_of_stock_skus": {
                        "$sum": {"$cond": [{"$lte": ["$stock_count", 0]}, 1, 0]}
                    },
                    "low_stock_skus": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$gt": ["$stock_count", 0]},
                                        {"$lte": ["$stock_count", "$min_stock_alert"]}
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    },
                    "in_stock_skus": {
                        "$sum": {
                            "$cond": [
                                {"$gt": ["$stock_count", "$min_stock_alert"]},
                                1,
                                0
                            ]
                        }
                    }
                }
            }
        ]

        sku_stats = await self.db.medicines.aggregate(sku_pipeline).to_list(1)
        base = sku_stats[0] if sku_stats else {
            "total_skus": 0,
            "total_stock_units": 0,
            "total_valuation_bdt": 0.0,
            "in_stock_skus": 0,
            "low_stock_skus": 0,
            "out_of_stock_skus": 0
        }

        # Batch counts
        active_batches = await self.db.inventory_batches.count_documents({
            "quantity_available": {"$gt": 0}
        })
        expiring_soon_batches = await self.db.inventory_batches.count_documents({
            "quantity_available": {"$gt": 0},
            "expiry_date": {"$gt": now, "$lte": soon_threshold}
        })
        expired_batches = await self.db.inventory_batches.count_documents({
            "quantity_available": {"$gt": 0},
            "expiry_date": {"$lte": now}
        })

        total_skus = base.get("total_skus", 0)
        in_stock_skus = base.get("in_stock_skus", 0)
        low_stock_skus = base.get("low_stock_skus", 0)
        out_of_stock_skus = base.get("out_of_stock_skus", 0)

        return {
            "total_skus": total_skus,
            "total_items": total_skus,
            "total_stock_units": base.get("total_stock_units", 0),
            "total_valuation_bdt": round(float(base.get("total_valuation_bdt", 0.0)), 2),
            "in_stock_skus": in_stock_skus,
            "in_stock_count": in_stock_skus,
            "low_stock_skus": low_stock_skus,
            "low_stock_count": low_stock_skus,
            "out_of_stock_skus": out_of_stock_skus,
            "out_of_stock_count": out_of_stock_skus,
            "active_batches": active_batches,
            "active_batches_count": active_batches,
            "expiring_soon_batches": expiring_soon_batches,
            "expiring_soon_count": expiring_soon_batches,
            "expired_batches": expired_batches,
            "expired_count": expired_batches
        }

    async def get_inventory_items(
        self,
        search: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        sort_by: Optional[str] = "stock_desc",
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}

        if search:
            escaped = re.escape(search.strip())
            pattern = re.compile(escaped, re.IGNORECASE)
            match["$or"] = [
                {"brand": pattern},
                {"name": pattern},
                {"medicine_name": pattern},
                {"generic_name": pattern},
                {"manufacturer": pattern}
            ]

        if category and category != "ALL":
            match["$or"] = [
                {"category": category},
                {"category_slug": category.lower()}
            ]

        pipeline: List[Dict[str, Any]] = [{"$match": match}]

        # Add fields for status computing
        pipeline.append({
            "$addFields": {
                "resolved_stock": {"$ifNull": ["$stock_count", 0]},
                "resolved_min": {"$ifNull": ["$min_stock_alert", 10]},
                "item_status": {
                    "$cond": [
                        {"$lte": [{"$ifNull": ["$stock_count", 0]}, 0]},
                        "OUT_OF_STOCK",
                        {
                            "$cond": [
                                {
                                    "$lte": [
                                        {"$ifNull": ["$stock_count", 0]},
                                        {"$ifNull": ["$min_stock_alert", 10]}
                                    ]
                                },
                                "LOW_STOCK",
                                "IN_STOCK"
                            ]
                        }
                    ]
                }
            }
        })

        if status and status != "ALL":
            pipeline.append({"$match": {"item_status": status}})

        # Sorting
        sort_stage: Dict[str, Any] = {}
        if sort_by == "stock_asc":
            sort_stage = {"resolved_stock": 1, "brand": 1}
        elif sort_by == "stock_desc":
            sort_stage = {"resolved_stock": -1, "brand": 1}
        elif sort_by == "name_asc":
            sort_stage = {"brand": 1}
        elif sort_by == "name_desc":
            sort_stage = {"brand": -1}
        elif sort_by == "valuation_desc":
            sort_stage = {"unit_price": -1, "resolved_stock": -1}
        else:
            sort_stage = {"resolved_stock": -1}

        pipeline.append({"$sort": sort_stage})

        # Count total matching
        count_pipeline = pipeline + [{"$count": "total"}]
        count_res = await self.db.medicines.aggregate(count_pipeline).to_list(1)
        total = count_res[0]["total"] if count_res else 0

        # Pagination
        skip = (page - 1) * limit
        pipeline.append({"$skip": skip})
        pipeline.append({"$limit": limit})

        # Lookup batch details for active medicine items
        pipeline.append({
            "$lookup": {
                "from": "inventory_batches",
                "let": {"med_id": {"$ifNull": ["$id", {"$toString": "$_id"}]}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$medicine_id", "$$med_id"]},
                                    {"$gt": ["$quantity_available", 0]}
                                ]
                            }
                        }
                    },
                    {"$sort": {"expiry_date": 1}}
                ],
                "as": "batches"
            }
        })

        raw_items = await self.db.medicines.aggregate(pipeline).to_list(limit)

        items = []
        for doc in raw_items:
            med_id = doc.get("id") or str(doc.get("_id", ""))
            batches = doc.get("batches", [])
            earliest_expiry = batches[0]["expiry_date"] if batches else None

            items.append({
                "id": med_id,
                "name": doc.get("name") or doc.get("medicine_name") or doc.get("brand") or "Unnamed Medicine",
                "brand": doc.get("brand") or doc.get("name") or "Medicine",
                "generic_name": doc.get("generic_name") or "N/A",
                "strength": doc.get("strength") or "",
                "dosage_form": doc.get("dosage_form") or "Tablet",
                "category": doc.get("category") or "TABLET",
                "manufacturer": doc.get("manufacturer") or doc.get("manufacturer_name") or "General Pharma",
                "unit_price": float(doc.get("unit_price") or 0.0),
                "stock_count": int(doc.get("resolved_stock", 0)),
                "available_count": int(doc.get("resolved_stock", 0)),
                "min_stock_alert": int(doc.get("resolved_min", 10)),
                "reorder_quantity": int(doc.get("reorder_quantity") or 50),
                "shelf_location": doc.get("shelf_location") or "Main Storage",
                "in_stock": int(doc.get("resolved_stock", 0)) > 0,
                "requires_prescription": bool(doc.get("requires_prescription") or doc.get("rx_required")),
                "medicine_image": doc.get("medicine_image") or doc.get("image") or doc.get("image_url"),
                "image_url": doc.get("medicine_image") or doc.get("image") or doc.get("image_url"),
                "batch_count": len(batches),
                "earliest_expiry": earliest_expiry,
                "status": doc.get("item_status", "IN_STOCK")
            })

        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }

    async def get_medicine_by_id_or_slug(self, identifier: str) -> Optional[Dict[str, Any]]:
        return await self.db.medicines.find_one({
            "$or": [
                {"id": identifier},
                {"slug": identifier}
            ]
        })

    async def update_medicine_stock_and_flags(
        self,
        medicine_id: str,
        delta: int,
        set_stock: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        if set_stock is not None:
            new_stock = max(0, set_stock)
            in_stock = new_stock > 0
            return await self.db.medicines.find_one_and_update(
                {"$or": [{"id": medicine_id}, {"slug": medicine_id}]},
                {"$set": {
                    "stock_count": new_stock,
                    "in_stock": in_stock,
                    "is_available": in_stock,
                    "updated_at": datetime.now(timezone.utc)
                }},
                return_document=True
            )
        else:
            # Atomic increment
            res = await self.db.medicines.find_one_and_update(
                {"$or": [{"id": medicine_id}, {"slug": medicine_id}]},
                {"$inc": {"stock_count": delta}},
                return_document=True
            )
            if res:
                cur_stock = res.get("stock_count", 0)
                in_stock = cur_stock > 0
                filter_q = {"_id": res["_id"]} if "_id" in res else {"$or": [{"id": medicine_id}, {"slug": medicine_id}]}
                return await self.db.medicines.find_one_and_update(
                    filter_q,
                    {"$set": {
                        "in_stock": in_stock,
                        "is_available": in_stock,
                        "updated_at": datetime.now(timezone.utc)
                    }},
                    return_document=True
                )
            return None

    async def update_thresholds(
        self,
        medicine_id: str,
        min_stock_alert: Optional[int],
        reorder_quantity: Optional[int],
        shelf_location: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        updates: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if min_stock_alert is not None:
            updates["min_stock_alert"] = min_stock_alert
        if reorder_quantity is not None:
            updates["reorder_quantity"] = reorder_quantity
        if shelf_location is not None:
            updates["shelf_location"] = shelf_location

        return await self.db.medicines.find_one_and_update(
            {"$or": [{"id": medicine_id}, {"slug": medicine_id}]},
            {"$set": updates},
            return_document=True
        )

    # =========================================================================
    # Batches (FEFO)
    # =========================================================================
    async def create_batch(self, batch_data: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in batch_data:
            batch_data["id"] = str(uuid.uuid4())
        batch_data["created_at"] = datetime.now(timezone.utc)
        batch_data["updated_at"] = datetime.now(timezone.utc)
        await self.db.inventory_batches.insert_one(batch_data)
        return batch_data

    async def find_batch_by_id(self, batch_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.inventory_batches.find_one({"id": batch_id})

    async def get_batches_for_medicine(self, medicine_id: str) -> List[Dict[str, Any]]:
        cursor = self.db.inventory_batches.find({
            "medicine_id": medicine_id
        }).sort("expiry_date", 1)
        return await cursor.to_list(100)

    async def get_all_batches(
        self,
        search: Optional[str] = None,
        filter_status: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        match: Dict[str, Any] = {}

        if search:
            escaped = re.escape(search.strip())
            pattern = re.compile(escaped, re.IGNORECASE)
            match["$or"] = [
                {"medicine_name": pattern},
                {"batch_number": pattern},
                {"supplier_name": pattern},
                {"supplier_invoice_no": pattern}
            ]

        if filter_status == "EXPIRING_SOON":
            match["expiry_date"] = {"$gt": now, "$lte": now + timedelta(days=60)}
            match["quantity_available"] = {"$gt": 0}
        elif filter_status == "EXPIRED":
            match["expiry_date"] = {"$lte": now}
            match["quantity_available"] = {"$gt": 0}
        elif filter_status == "ACTIVE":
            match["quantity_available"] = {"$gt": 0}
            match["expiry_date"] = {"$gt": now}
        elif filter_status == "DEPLETED":
            match["quantity_available"] = {"$lte": 0}

        total = await self.db.inventory_batches.count_documents(match)
        skip = (page - 1) * limit
        cursor = self.db.inventory_batches.find(match).sort("expiry_date", 1).skip(skip).limit(limit)
        docs = await cursor.to_list(limit)

        items = []
        for b in docs:
            exp_date = b.get("expiry_date")
            days_left = 0
            if exp_date:
                if exp_date.tzinfo is None:
                    exp_date = exp_date.replace(tzinfo=timezone.utc)
                days_left = (exp_date - now).days

            status = "ACTIVE"
            if b.get("quantity_available", 0) <= 0:
                status = "DEPLETED"
            elif days_left < 0:
                status = "EXPIRED"
            elif days_left <= 60:
                status = "EXPIRING_SOON"

            items.append({
                "id": b.get("id"),
                "medicine_id": b.get("medicine_id"),
                "medicine_name": b.get("medicine_name", "Medicine"),
                "batch_number": b.get("batch_number"),
                "expiry_date": exp_date,
                "manufacturing_date": b.get("manufacturing_date"),
                "supplier_name": b.get("supplier_name", "Unknown Supplier"),
                "supplier_invoice_no": b.get("supplier_invoice_no"),
                "quantity_received": b.get("quantity_received", 0),
                "quantity_available": b.get("quantity_available", 0),
                "quantity_sold": b.get("quantity_sold", 0),
                "quantity_discarded": b.get("quantity_discarded", 0),
                "purchase_price_bdt": float(b.get("purchase_price_bdt", 0.0)),
                "mrp_bdt": float(b.get("mrp_bdt", 0.0)),
                "status": status,
                "created_at": b.get("created_at") or now,
                "days_until_expiry": days_left
            })

        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }

    async def update_batch_quantity(
        self,
        batch_id: str,
        delta: int
    ) -> Optional[Dict[str, Any]]:
        return await self.db.inventory_batches.find_one_and_update(
            {"id": batch_id},
            {
                "$inc": {"quantity_available": delta},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            },
            return_document=True
        )

    # =========================================================================
    # Transactions (Stock Movement Ledger)
    # =========================================================================
    async def create_transaction(self, tx_data: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in tx_data:
            tx_data["id"] = str(uuid.uuid4())
        if "created_at" not in tx_data:
            tx_data["created_at"] = datetime.now(timezone.utc)
        await self.db.inventory_transactions.insert_one(tx_data)
        return tx_data

    async def get_transactions(
        self,
        medicine_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if medicine_id:
            match["medicine_id"] = medicine_id
        if transaction_type and transaction_type != "ALL":
            match["transaction_type"] = transaction_type
        if search:
            escaped = re.escape(search.strip())
            pattern = re.compile(escaped, re.IGNORECASE)
            match["$or"] = [
                {"medicine_name": pattern},
                {"batch_number": pattern},
                {"reference_id": pattern},
                {"actor_name": pattern},
                {"reason": pattern}
            ]

        total = await self.db.inventory_transactions.count_documents(match)
        skip = (page - 1) * limit
        cursor = self.db.inventory_transactions.find(match).sort("created_at", -1).skip(skip).limit(limit)
        docs = await cursor.to_list(limit)

        items = []
        for d in docs:
            items.append({
                "id": d.get("id"),
                "medicine_id": d.get("medicine_id"),
                "medicine_name": d.get("medicine_name", "Medicine"),
                "batch_id": d.get("batch_id"),
                "batch_number": d.get("batch_number"),
                "transaction_type": d.get("transaction_type"),
                "quantity_delta": d.get("quantity_delta", 0),
                "previous_stock": d.get("previous_stock", 0),
                "new_stock": d.get("new_stock", 0),
                "reference_id": d.get("reference_id"),
                "actor_id": d.get("actor_id"),
                "actor_name": d.get("actor_name") or "System",
                "reason": d.get("reason"),
                "created_at": d.get("created_at") or datetime.now(timezone.utc)
            })

        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
