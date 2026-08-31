from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.pharmacy.crawler import MedEasyCrawlerManager
from app.modules.pharmacy.schemas import (
    MedicineResponse,
    MedicineFilterParams,
    CreateMedicineRequest,
    UpdateMedicineRequest,
    CategorySummaryResponse,
    MedicineDetailResponse,
    CrawlerSettingsModel,
    UpdateCrawlerSettingsRequest,
    CrawlerStartRequest,
    CrawlerJobStatusResponse,
    PharmacyStatsResponse
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.enums import AuditAction
from app.core.exceptions import NotFoundException
from app.core.logging import log_audit_event

class PharmacyService:
    def __init__(self, repo: PharmacyRepository, db: AsyncIOMotorDatabase):
        self.repo = repo
        self.db = db
        self.crawler = MedEasyCrawlerManager.get_instance()

    async def search_catalog(
        self,
        filters: MedicineFilterParams,
        pagination: PaginationParams
    ) -> PaginatedResponse[MedicineResponse]:
        docs, total = await self.repo.search_medicines(
            filters=filters,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = []
        for d in docs:
            item_dict = dict(d)
            if not item_dict.get("medicine_name"):
                item_dict["medicine_name"] = item_dict.get("brand") or item_dict.get("name") or "Unknown"
            if not item_dict.get("name"):
                item_dict["name"] = f"{item_dict.get('brand', '')} {item_dict.get('strength', '')}".strip() or item_dict["medicine_name"]
            mfg = item_dict.get("manufacturer_name")
            if not mfg or str(mfg).isdigit():
                mfg_candidate = item_dict.get("manufacturer")
                if mfg_candidate and not str(mfg_candidate).isdigit():
                    mfg = str(mfg_candidate)
                elif item_dict.get("brand") and not str(item_dict.get("brand")).isdigit():
                    mfg = str(item_dict.get("brand"))
                else:
                    mfg = ""
            item_dict["manufacturer_name"] = mfg
            if not item_dict.get("brand"):
                item_dict["brand"] = item_dict.get("name") or item_dict.get("medicine_name") or "Unknown"
            if item_dict.get("generic_name") is None:
                item_dict["generic_name"] = ""
            if item_dict.get("dosage_form") is None:
                item_dict["dosage_form"] = "Tablet"
            if item_dict.get("strength") is None:
                item_dict["strength"] = ""
            if item_dict.get("pack_size") is None:
                item_dict["pack_size"] = "1 Unit"
            if item_dict.get("unit_price") is None:
                item_dict["unit_price"] = 0.0

            # Sanitize unit_prices list
            if "unit_prices" in item_dict and isinstance(item_dict["unit_prices"], list):
                sanitized_prices = []
                for p in item_dict["unit_prices"]:
                    if isinstance(p, dict):
                        sanitized_prices.append({
                            "id": p.get("id"),
                            "unit": p.get("unit") or "Unit",
                            "unit_size": int(p.get("unit_size") or 1),
                            "price": float(p.get("price") or 0.0)
                        })
                item_dict["unit_prices"] = sanitized_prices
            else:
                item_dict["unit_prices"] = []

            items.append(MedicineResponse(**item_dict))

        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_medicine_by_id_or_slug(self, identifier: str) -> MedicineResponse:
        doc = await self.repo.get_by_slug(identifier)
        if not doc:
            doc = await self.repo.get_by_id(identifier)
        if not doc or not doc.get("is_active", True):
            raise NotFoundException(f"Medicine '{identifier}' not found")

        item_dict = dict(doc)
        if not item_dict.get("medicine_name"):
            item_dict["medicine_name"] = item_dict.get("brand") or item_dict.get("name") or "Unknown"
        if not item_dict.get("name"):
            item_dict["name"] = f"{item_dict.get('brand', '')} {item_dict.get('strength', '')}".strip() or item_dict["medicine_name"]
        mfg = item_dict.get("manufacturer_name")
        if not mfg or str(mfg).isdigit():
            mfg_candidate = item_dict.get("manufacturer")
            if mfg_candidate and not str(mfg_candidate).isdigit():
                mfg = str(mfg_candidate)
            elif item_dict.get("brand") and not str(item_dict.get("brand")).isdigit():
                mfg = str(item_dict.get("brand"))
            else:
                mfg = ""
        item_dict["manufacturer_name"] = mfg
        if not item_dict.get("brand"):
            item_dict["brand"] = item_dict.get("name") or item_dict.get("medicine_name") or "Unknown"
        if item_dict.get("generic_name") is None:
            item_dict["generic_name"] = ""
        if item_dict.get("dosage_form") is None:
            item_dict["dosage_form"] = "Tablet"
        if item_dict.get("strength") is None:
            item_dict["strength"] = ""
        if item_dict.get("pack_size") is None:
            item_dict["pack_size"] = "1 Unit"
        if item_dict.get("unit_price") is None:
            item_dict["unit_price"] = 0.0

        if "unit_prices" in item_dict and isinstance(item_dict["unit_prices"], list):
            sanitized_prices = []
            for p in item_dict["unit_prices"]:
                if isinstance(p, dict):
                    sanitized_prices.append({
                        "id": p.get("id"),
                        "unit": p.get("unit") or "Unit",
                        "unit_size": int(p.get("unit_size") or 1),
                        "price": float(p.get("price") or 0.0)
                    })
            item_dict["unit_prices"] = sanitized_prices
        else:
            item_dict["unit_prices"] = []

        return MedicineResponse(**item_dict)

    async def get_medicine_details(self, slug: str) -> MedicineDetailResponse:
        details_doc = await self.repo.get_details_by_slug(slug)
        if details_doc:
            # Reconstruct response from full monograph doc
            return MedicineDetailResponse(
                id=str(details_doc.get("id", "")),
                medicine_id=str(details_doc.get("medicine_id", "")),
                slug=details_doc.get("slug") or slug,
                medicine_name=details_doc.get("medicine_name", "Medicine"),
                generic_name=details_doc.get("generic_name", ""),
                category_name=details_doc.get("category_name", "Tablet"),
                category_slug=details_doc.get("category_slug", "otc-medicine"),
                manufacturer_name=details_doc.get("manufacturer_name") or details_doc.get("product_info", {}).get("manufacturer_name"),
                meta_title=details_doc.get("meta_title"),
                meta_description=details_doc.get("meta_description"),
                product_info=details_doc.get("product_info", {}),
                medicine_details=details_doc.get("medicine_details", {}),
                related_medicines=details_doc.get("related_medicines", [])
            )

        # Fallback to catalogue search
        med = await self.repo.find_by_id_or_slug(slug)
        if not med:
            med = await self.repo.get_by_slug(slug)
        if not med:
            med = await self.repo.get_by_id(slug)
        if not med:
            raise NotFoundException(f"Medicine details for '{slug}' not found")

        med_name = med.get("medicine_name") or med.get("brand") or "Unknown"
        mfg = med.get("manufacturer_name")
        if not mfg or str(mfg).isdigit():
            mfg_candidate = med.get("manufacturer")
            if mfg_candidate and not str(mfg_candidate).isdigit():
                mfg = str(mfg_candidate)
            elif med.get("brand") and not str(med.get("brand")).isdigit():
                mfg = str(med.get("brand"))
            else:
                mfg = None

        return MedicineDetailResponse(
            id=str(med.get("id", "")),
            medicine_id=str(med.get("id", "")),
            slug=med.get("slug") or slug,
            medicine_name=med_name,
            generic_name=med.get("generic_name") or "",
            category_name=med.get("category_name") or "Tablet",
            category_slug=med.get("category_slug") or "otc-medicine",
            manufacturer_name=mfg,
            meta_title=f"{med_name} - Price, Uses & Side Effects",
            meta_description=f"Information on {med_name} ({med.get('generic_name') or ''})",
            product_info=med,
            medicine_details={},
            related_medicines=[]
        )

    async def get_medicine_detail(self, slug: str) -> MedicineDetailResponse:
        return await self.get_medicine_details(slug)

    async def get_categories_summary(self) -> List[CategorySummaryResponse]:
        summary = await self.repo.get_categories_summary()
        return [CategorySummaryResponse(**s) for s in summary]

    async def get_pharmacy_stats(self) -> PharmacyStatsResponse:
        stats = await self.repo.get_pharmacy_stats()
        # Check live crawler status
        crawler_status = await self.crawler.get_status(self.db)
        if crawler_status.is_running:
            stats["crawler_status"] = "RUNNING"
        return PharmacyStatsResponse(**stats)

    # =========================================================================
    # Crawler Control & Configuration
    # =========================================================================
    async def get_crawler_settings(self) -> CrawlerSettingsModel:
        return await self.repo.get_crawler_settings()

    async def update_crawler_settings(
        self,
        req: UpdateCrawlerSettingsRequest,
        admin_id: str
    ) -> CrawlerSettingsModel:
        updates = req.model_dump(exclude_unset=True)
        updated = await self.repo.update_crawler_settings(updates)

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.SETTINGS_UPDATED,
            target_type="CRAWLER_SETTINGS",
            target_id="default_settings",
            details={"updated_fields": list(updates.keys())}
        )

        return updated

    async def start_crawler(
        self,
        req: CrawlerStartRequest,
        admin_id: str
    ) -> CrawlerJobStatusResponse:
        settings = await self.repo.get_crawler_settings()
        category = req.category_slug or settings.category_slug

        status = await self.crawler.start_crawler(
            db=self.db,
            settings=settings,
            category_slug=category,
            start_page=req.start_page,
            max_pages=req.max_pages or settings.max_pages,
            admin_id=admin_id
        )

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.MEDEASY_INGESTION_TRIGGERED,
            target_type="CRAWLER",
            target_id=status.job_id or "job",
            details={"category_slug": category, "start_page": req.start_page}
        )

        return status

    async def stop_crawler(self, admin_id: str) -> CrawlerJobStatusResponse:
        status = await self.crawler.stop_crawler()
        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.MEDICINE_UPDATED,
            target_type="CRAWLER",
            target_id=status.job_id or "job",
            details={"action": "STOPPED"}
        )
        return status

    async def get_crawler_status(self) -> CrawlerJobStatusResponse:
        return await self.crawler.get_status(self.db)

    async def get_crawler_stream(self):
        return self.crawler.subscribe_stream()

    async def get_crawler_history(self) -> List[Dict[str, Any]]:
        return await self.repo.get_crawler_job_history(limit=10)

    # =========================================================================
    # Admin Manual CRUD
    # =========================================================================
    async def create_medicine(self, req: CreateMedicineRequest, admin_id: Optional[str] = None) -> MedicineResponse:
        doc = req.model_dump()
        doc["category"] = req.category.value if hasattr(req.category, "value") else req.category
        created = await self.repo.create_medicine(doc)

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.MEDICINE_CREATED,
            target_type="MEDICINE",
            target_id=created["id"],
            details={"brand": created["brand"], "price": created["unit_price"]}
        )

        return MedicineResponse(**created)

    async def update_medicine(self, medicine_id: str, req: UpdateMedicineRequest, admin_id: Optional[str] = None) -> MedicineResponse:
        updates = req.model_dump(exclude_unset=True)
        updated = await self.repo.update_medicine(medicine_id, updates)
        if not updated:
            raise NotFoundException("Medicine not found")

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.MEDICINE_UPDATED,
            target_type="MEDICINE",
            target_id=medicine_id,
            details={"updated_fields": list(updates.keys())}
        )

        return MedicineResponse(**updated)

    async def delete_medicine(self, medicine_id_or_slug: str, admin_id: Optional[str] = None) -> bool:
        med = await self.repo.find_by_id_or_slug(medicine_id_or_slug)
        if not med:
            raise NotFoundException("Medicine not found")

        deleted = await self.repo.delete_medicine(medicine_id_or_slug)
        if deleted:
            await log_audit_event(
                self.db,
                user_id=admin_id,
                action=AuditAction.MEDICINE_DELETED,
                target_type="MEDICINE",
                target_id=med.get("id") or medicine_id_or_slug,
                details={"brand": med.get("brand"), "slug": med.get("slug")}
            )
        return deleted

    async def delete_medicines_bulk(self, ids_or_slugs: List[str], admin_id: Optional[str] = None) -> int:
        if not ids_or_slugs:
            return 0
        count = await self.repo.delete_medicines_bulk(ids_or_slugs)
        if count > 0:
            await log_audit_event(
                self.db,
                user_id=admin_id,
                action=AuditAction.MEDICINES_BULK_DELETED,
                target_type="MEDICINE",
                target_id="BULK",
                details={"deleted_count": count, "targets": ids_or_slugs[:20]}
            )
        return count

    # =========================================================================
    # Admin Inventory & Stock Management
    # =========================================================================
    async def update_stock(
        self,
        medicine_id_or_slug: str,
        stock_count: int,
        in_stock: Optional[bool] = None,
        admin_id: Optional[str] = None
    ) -> MedicineResponse:
        med = await self.repo.find_by_id_or_slug(medicine_id_or_slug)
        if not med:
            raise NotFoundException("Medicine not found")

        med_id = med.get("id") or medicine_id_or_slug
        resolved_in_stock = in_stock if in_stock is not None else (stock_count > 0)

        updates = {
            "stock_count": stock_count,
            "in_stock": resolved_in_stock,
            "is_available": resolved_in_stock
        }

        updated = await self.repo.update_medicine(med_id, updates)
        if not updated:
            raise NotFoundException("Medicine not found")

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.MEDICINE_UPDATED,
            target_type="INVENTORY",
            target_id=med_id,
            details={"brand": updated.get("brand"), "stock_count": stock_count, "in_stock": resolved_in_stock}
        )

        return MedicineResponse(**updated)

    async def batch_update_stock(
        self,
        items: List[Dict[str, Any]],
        admin_id: Optional[str] = None
    ) -> int:
        updated_count = 0
        for it in items:
            med_id = it.get("medicine_id")
            stock_count = it.get("stock_count", 0)
            if not med_id:
                continue
            in_stock = stock_count > 0
            res = await self.db.medicines.update_one(
                {"id": med_id},
                {"$set": {"stock_count": stock_count, "in_stock": in_stock, "is_available": in_stock}}
            )
            if res.modified_count > 0:
                updated_count += 1

        if updated_count > 0:
            await log_audit_event(
                self.db,
                user_id=admin_id,
                action=AuditAction.MEDICINE_UPDATED,
                target_type="INVENTORY",
                target_id="BATCH",
                details={"updated_count": updated_count}
            )

        return updated_count
