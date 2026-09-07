from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.common.enums import StockMovementType, BatchStatus

class InventoryOverviewResponse(BaseModel):
    total_skus: int = 0
    total_items: int = 0
    total_stock_units: int = 0
    total_valuation_bdt: float = 0.0
    in_stock_skus: int = 0
    in_stock_count: int = 0
    low_stock_skus: int = 0
    low_stock_count: int = 0
    out_of_stock_skus: int = 0
    out_of_stock_count: int = 0
    active_batches: int = 0
    active_batches_count: int = 0
    expiring_soon_batches: int = 0
    expiring_soon_count: int = 0
    expired_batches: int = 0
    expired_count: int = 0

class InventoryItemResponse(BaseModel):
    id: str
    name: str
    brand: str
    generic_name: str
    strength: str
    dosage_form: str
    category: str
    manufacturer: str
    unit_price: float
    stock_count: int
    available_count: int
    min_stock_alert: int
    reorder_quantity: int
    shelf_location: Optional[str] = "Main Storage"
    in_stock: bool
    requires_prescription: bool
    medicine_image: Optional[str] = None
    image_url: Optional[str] = None
    batch_count: int = 0
    earliest_expiry: Optional[datetime] = None
    status: str = "IN_STOCK"  # IN_STOCK, LOW_STOCK, OUT_OF_STOCK

class RestockRequest(BaseModel):
    medicine_id: str = Field(..., min_length=1)
    batch_number: str = Field(..., min_length=1)
    expiry_date: datetime
    manufacturing_date: Optional[datetime] = None
    supplier_name: str = Field(..., min_length=1)
    supplier_invoice_no: Optional[str] = ""
    quantity_received: int = Field(..., gt=0)
    purchase_price_bdt: float = Field(..., ge=0.0)
    mrp_bdt: Optional[float] = None
    notes: Optional[str] = ""

class StockAdjustmentRequest(BaseModel):
    medicine_id: str = Field(..., min_length=1)
    batch_id: Optional[str] = None
    movement_type: StockMovementType = StockMovementType.MANUAL_ADJUSTMENT
    quantity_delta: int = Field(..., description="Positive for addition, negative for deduction")
    reason: str = Field(..., min_length=2)
    notes: Optional[str] = ""

class UpdateItemThresholdsRequest(BaseModel):
    min_stock_alert: Optional[int] = Field(None, ge=0)
    reorder_quantity: Optional[int] = Field(None, ge=0)
    shelf_location: Optional[str] = None

class InventoryBatchResponse(BaseModel):
    id: str
    medicine_id: str
    medicine_name: str
    batch_number: str
    expiry_date: datetime
    manufacturing_date: Optional[datetime] = None
    supplier_name: str
    supplier_invoice_no: Optional[str] = None
    quantity_received: int
    quantity_available: int
    quantity_sold: int = 0
    quantity_discarded: int = 0
    purchase_price_bdt: float = 0.0
    mrp_bdt: float = 0.0
    status: str = "ACTIVE"
    created_at: datetime
    days_until_expiry: int

class InventoryTransactionResponse(BaseModel):
    id: str
    medicine_id: str
    medicine_name: str
    batch_id: Optional[str] = None
    batch_number: Optional[str] = None
    transaction_type: str
    quantity_delta: int
    previous_stock: int
    new_stock: int
    reference_id: Optional[str] = None
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime
