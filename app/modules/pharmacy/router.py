from fastapi import APIRouter, Depends, Query, status
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.pharmacy.service import PharmacyService
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
from app.common.enums import UserRole
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/pharmacy", tags=["E-Pharmacy & Crawler"])

def get_pharmacy_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> PharmacyService:
    repo = PharmacyRepository(db)
    return PharmacyService(repo, db)

# =========================================================================
# Medicine Catalog & Discovery
# =========================================================================
@router.get("/medicines", response_model=APIResponse[PaginatedResponse[MedicineResponse]])
async def search_medicines(
    search: Optional[str] = Query(None),
    generic_name: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    category_slug: Optional[str] = Query(None),
    category_name: Optional[str] = Query(None),
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
        category_slug=category_slug,
        category_name=category_name,
        requires_prescription=requires_prescription,
        in_stock_only=in_stock_only,
        min_price=min_price,
        max_price=max_price,
        manufacturer=manufacturer
    )
    pagination = PaginationParams(page=page, limit=limit)
    res = await service.search_catalog(filters, pagination)
    return APIResponse(success=True, message="Medicines retrieved", data=res)

@router.get("/medicines/{slug_or_id}", response_model=APIResponse[MedicineResponse])
async def get_medicine(
    slug_or_id: str,
    service: PharmacyService = Depends(get_pharmacy_service)
):
    med = await service.get_medicine_by_id_or_slug(slug_or_id)
    return APIResponse(success=True, message="Medicine retrieved", data=med)

@router.get("/medicines/{slug}/details", response_model=APIResponse[MedicineDetailResponse])
async def get_medicine_details(
    slug: str,
    service: PharmacyService = Depends(get_pharmacy_service)
):
    detail = await service.get_medicine_detail(slug)
    return APIResponse(success=True, message="Medicine monograph details retrieved", data=detail)

@router.get("/categories", response_model=APIResponse[List[CategorySummaryResponse]])
async def get_categories(
    service: PharmacyService = Depends(get_pharmacy_service)
):
    categories = await service.get_categories_summary()
    return APIResponse(success=True, message="Categories retrieved", data=categories)

@router.get("/stats", response_model=APIResponse[PharmacyStatsResponse])
async def get_pharmacy_stats(
    service: PharmacyService = Depends(get_pharmacy_service)
):
    stats = await service.get_pharmacy_stats()
    return APIResponse(success=True, message="Pharmacy stats retrieved", data=stats)

# =========================================================================
# Crawler Control & Configuration Endpoints
# =========================================================================
@router.get("/crawler/settings", response_model=APIResponse[CrawlerSettingsModel])
async def get_crawler_settings(
    service: PharmacyService = Depends(get_pharmacy_service)
):
    settings = await service.get_crawler_settings()
    return APIResponse(success=True, message="Crawler settings retrieved", data=settings)

@router.put("/crawler/settings", response_model=APIResponse[CrawlerSettingsModel])
async def update_crawler_settings(
    req: UpdateCrawlerSettingsRequest,
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can update crawler settings")
    settings = await service.update_crawler_settings(req, admin_id=payload["sub"])
    return APIResponse(success=True, message="Crawler settings updated successfully", data=settings)

@router.post("/crawler/start", response_model=APIResponse[CrawlerJobStatusResponse])
async def start_crawler(
    req: CrawlerStartRequest = CrawlerStartRequest(),
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can trigger the MedEasy medicine crawler")
    status_res = await service.start_crawler(req, admin_id=payload["sub"])
    return APIResponse(success=True, message="MedEasy crawler initiated", data=status_res)

@router.post("/crawler/stop", response_model=APIResponse[CrawlerJobStatusResponse])
async def stop_crawler(
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can stop crawler execution")
    status_res = await service.stop_crawler(admin_id=payload["sub"])
    return APIResponse(success=True, message="Crawler stop requested", data=status_res)

from fastapi.responses import StreamingResponse

@router.get("/crawler/stream")
async def stream_crawler_events(
    service: PharmacyService = Depends(get_pharmacy_service)
):
    """Real-time SSE event stream for live crawling progress, item injection, and logs."""
    generator = await service.get_crawler_stream()
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@router.get("/crawler/status", response_model=APIResponse[CrawlerJobStatusResponse])
async def get_crawler_status(
    service: PharmacyService = Depends(get_pharmacy_service)
):
    status_res = await service.get_crawler_status()
    return APIResponse(success=True, message="Crawler status retrieved", data=status_res)

@router.get("/crawler/history", response_model=APIResponse[List[Dict[str, Any]]])
async def get_crawler_history(
    payload: dict = Depends(get_current_user_payload),
    service: PharmacyService = Depends(get_pharmacy_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can view crawler history")
    history = await service.get_crawler_history()
    return APIResponse(success=True, message="Crawler history retrieved", data=history)

# =========================================================================
# Admin Manual CRUD Endpoints
# =========================================================================
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
