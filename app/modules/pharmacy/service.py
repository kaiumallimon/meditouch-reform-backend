from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.pharmacy.schemas import (
    MedicineResponse,
    MedicineFilterParams,
    CreateMedicineRequest,
    UpdateMedicineRequest,
    CategorySummaryResponse
)
from app.integrations.medicine_source.medeasy_parser import ingest_medicine_catalog
from app.common.pagination import PaginationParams, PaginatedResponse
from app.core.exceptions import NotFoundException

class PharmacyService:
    def __init__(self, repo: PharmacyRepository, db: AsyncIOMotorDatabase):
        self.repo = repo
        self.db = db

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
        items = [MedicineResponse(**d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_medicine_by_id(self, medicine_id: str) -> MedicineResponse:
        doc = await self.repo.get_by_id(medicine_id)
        if not doc or not doc.get("is_active", True):
            raise NotFoundException("Medicine not found")
        return MedicineResponse(**doc)

    async def get_categories_summary(self) -> List[CategorySummaryResponse]:
        summary = await self.repo.get_categories_summary()
        return [CategorySummaryResponse(**s) for s in summary]

    async def create_medicine(self, req: CreateMedicineRequest) -> MedicineResponse:
        doc = req.model_dump()
        doc["category"] = req.category.value if hasattr(req.category, "value") else req.category
        created = await self.repo.create_medicine(doc)
        return MedicineResponse(**created)

    async def update_medicine(self, medicine_id: str, req: UpdateMedicineRequest) -> MedicineResponse:
        updates = req.model_dump(exclude_unset=True)
        updated = await self.repo.update_medicine(medicine_id, updates)
        if not updated:
            raise NotFoundException("Medicine not found")
        return MedicineResponse(**updated)

    async def trigger_medeasy_ingestion(self) -> int:
        return await ingest_medicine_catalog(self.db)

