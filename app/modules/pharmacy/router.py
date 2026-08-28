from fastapi import APIRouter, Depends, Query, status
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.pharmacy.service import PharmacyService
from app.modules.pharmacy.schemas import (
    MedicineResponse,
    MedicineFilterParams,
    CreateMedicineRequest,
    UpdateMedicineRequest,
    CategorySummaryResponse
)
from app.common.enums import MedicineCategory, UserRole
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/pharmacy", tags=["E-Pharmacy Catalog"])

def get_pharmacy_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> PharmacyService:
    repo = PharmacyRepository(db)
    return PharmacyService(repo, db)

@router.get("/medicines", response_model=APIResponse[PaginatedResponse[MedicineResponse]])
async def search_medicines(
    search: Optional[str] = Query(None),
    generic_name: Optional[str] = Query(None),
    category: Optional[MedicineCategory] = Query(None),
    requires_prescription: Optional[bool] = Query(None),
    in_stock_only: Optional[bool] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    manufacturer: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    filters = MedicineFilterParams(
        search=search,
        generic_name=generic_name,
        category=category,
        requires_prescription=requires_prescription,
        in_stock_only=in_stock_only,
        min_price=min_price,
        max_price=max_price,
        manufacturer=manufacturer
    )
    pagination = PaginationParams(page=page, limit=limit)
    res = await service.search_catalog(filters, pagination)
    return APIResponse(success=True, message="Medicines retrieved", data=res)

@router.get("/medicines/{medicine_id}", response_model=APIResponse[MedicineResponse])
async def get_medicine(
    medicine_id: str,
    service: PharmacyService = Depends(get_pharmacy_service)
):
    med = await service.get_medicine_by_id(medicine_id)
    return APIResponse(success=True, message="Medicine details retrieved", data=med)

@router.get("/categories", response_model=APIResponse[List[CategorySummaryResponse]])
async def get_categories(
    service: PharmacyService = Depends(get_pharmacy_service)
):
    categories = await service.get_categories_summary()
    return APIResponse(success=True, message="Categories retrieved", data=categories)

@router.post("/admin/medicines", response_model=APIResponse[MedicineResponse], status_code=status.HTTP_201_CREATED)
async def create_medicine(
    req: CreateMedicineRequest,
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can create medicine records")
    med = await service.create_medicine(req, admin_id=payload["sub"])
    return APIResponse(success=True, message="Medicine created successfully", data=med)

@router.put("/admin/medicines/{medicine_id}", response_model=APIResponse[MedicineResponse])
async def update_medicine(
    medicine_id: str,
    req: UpdateMedicineRequest,
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can update medicine records")
    med = await service.update_medicine(medicine_id, req, admin_id=payload["sub"])
    return APIResponse(success=True, message="Medicine updated successfully", data=med)

@router.post("/admin/ingest-medeasy", response_model=APIResponse[dict])
async def ingest_medeasy(
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can trigger MedEasy catalog ingestion")
    count = await service.trigger_medeasy_ingestion(admin_id=payload["sub"])
    return APIResponse(success=True, message=f"Ingested/updated {count} medicines from MedEasy", data={"count": count})

