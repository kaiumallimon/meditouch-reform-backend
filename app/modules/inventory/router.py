from fastapi import APIRouter, Depends, Query, Response, status
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongodb import get_db
from app.modules.inventory.service import InventoryService
from app.modules.inventory.schemas import (
    InventoryOverviewResponse,
    RestockRequest,
    StockAdjustmentRequest,
    UpdateItemThresholdsRequest
)
from app.common.responses import APIResponse
from app.common.enums import UserRole
from app.core.security import get_current_user_payload
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/inventory", tags=["Pharmacy Inventory & Stocks"])

def get_inventory_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> InventoryService:
    return InventoryService(db)

def require_admin_or_staff(payload: dict = Depends(get_current_user_payload)) -> dict:
    role = payload.get("role")
    if role not in [UserRole.ADMIN.value, UserRole.DEVELOPER.value]:
        raise ForbiddenException("Only ADMIN or authorized staff can access inventory operations")
    return payload

@router.get("/overview", response_model=APIResponse[InventoryOverviewResponse])
async def get_inventory_overview(
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    data = await service.get_overview()
    return APIResponse(success=True, message="Inventory overview metrics retrieved", data=data)

@router.get("/items", response_model=APIResponse[dict])
async def list_inventory_items(
    search: Optional[str] = Query(None, description="Search brand, generic, manufacturer"),
    status: Optional[str] = Query("ALL", description="ALL, IN_STOCK, LOW_STOCK, OUT_OF_STOCK"),
    category: Optional[str] = Query("ALL", description="Filter by category"),
    sort_by: Optional[str] = Query("stock_desc", description="stock_desc, stock_asc, name_asc, name_desc, valuation_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    result = await service.get_items(
        search=search,
        status=status,
        category=category,
        sort_by=sort_by,
        page=page,
        limit=limit
    )
    return APIResponse(success=True, message="Inventory items retrieved", data=result)

@router.get("/items/{medicine_id}", response_model=APIResponse[dict])
async def get_inventory_item_details(
    medicine_id: str,
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    data = await service.get_item_details(medicine_id)
    return APIResponse(success=True, message="Item details and batches retrieved", data=data)

@router.post("/restock", response_model=APIResponse[dict])
async def receive_stock_inward(
    req: RestockRequest,
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    admin_id = payload.get("sub")
    admin_name = payload.get("name") or payload.get("email") or "Administrator"
    result = await service.restock(req, admin_id=admin_id, admin_name=admin_name)
    return APIResponse(success=True, message="Stock received and lot registered successfully", data=result)

@router.post("/adjust", response_model=APIResponse[dict])
async def adjust_stock_or_write_off(
    req: StockAdjustmentRequest,
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    admin_id = payload.get("sub")
    admin_name = payload.get("name") or payload.get("email") or "Administrator"
    result = await service.adjust_stock(req, admin_id=admin_id, admin_name=admin_name)
    return APIResponse(success=True, message="Stock adjusted and ledger recorded successfully", data=result)

@router.put("/items/{medicine_id}/thresholds", response_model=APIResponse[dict])
async def update_item_thresholds(
    medicine_id: str,
    req: UpdateItemThresholdsRequest,
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    result = await service.update_thresholds(medicine_id, req)
    return APIResponse(success=True, message=result["message"], data=result)

@router.get("/batches", response_model=APIResponse[dict])
async def list_batches(
    search: Optional[str] = Query(None, description="Search medicine, batch number, supplier"),
    status: Optional[str] = Query("ALL", description="ALL, ACTIVE, EXPIRING_SOON, EXPIRED, DEPLETED"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    result = await service.get_batches(search=search, filter_status=status, page=page, limit=limit)
    return APIResponse(success=True, message="Batches retrieved", data=result)

@router.get("/transactions", response_model=APIResponse[dict])
async def list_transactions(
    medicine_id: Optional[str] = Query(None, description="Filter by medicine ID"),
    type: Optional[str] = Query("ALL", description="Movement type"),
    search: Optional[str] = Query(None, description="Search reference, notes, actor"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    result = await service.get_transactions(
        medicine_id=medicine_id,
        transaction_type=type,
        search=search,
        page=page,
        limit=limit
    )
    return APIResponse(success=True, message="Inventory ledger transactions retrieved", data=result)

@router.get("/export", response_class=Response)
async def export_inventory_csv(
    payload: dict = Depends(require_admin_or_staff),
    service: InventoryService = Depends(get_inventory_service)
):
    csv_content = await service.export_inventory_csv()
    headers = {
        "Content-Disposition": "attachment; filename=meditouch_inventory_stocktake.csv"
    }
    return Response(content=csv_content, media_type="text/csv", headers=headers)
