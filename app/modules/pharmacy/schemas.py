from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.common.enums import MedicineCategory

class UnitPriceItem(BaseModel):
    id: Optional[Any] = None
    unit: str
    unit_size: int
    price: float

class MedicineResponse(BaseModel):
    id: str
    medeasy_id: Optional[Any] = None
    medicine_name: Optional[str] = None
    name: Optional[str] = None
    brand: str
    generic_name: str
    strength: str = ""
    dosage_form: str = "Tablet"
    category: Optional[str] = "TABLET"
    category_name: Optional[str] = "Tablet"
    category_slug: Optional[str] = "otc-medicine"
    slug: Optional[str] = None
    manufacturer: str = "Unknown Pharma"
    manufacturer_name: Optional[str] = None
    manufacturer_slug: Optional[str] = None
    unit_price: float = 0.0
    pack_size: str = "1 Unit"
    unit_prices: List[UnitPriceItem] = []
    discount_type: Optional[str] = "Percentage"
    discount_value: float = 0.0
    is_discountable: bool = False
    is_available: bool = True
    rx_required: bool = False
    requires_prescription: bool = False
    medicine_image: Optional[str] = None
    description: Optional[str] = None
    in_stock: bool = True
    stock_count: int = 100
    is_active: bool = True
    source: Optional[str] = "MedEasy"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class MedicineFilterParams(BaseModel):
    search: Optional[str] = None
    generic_name: Optional[str] = None
    category: Optional[str] = None
    category_slug: Optional[str] = None
    category_name: Optional[str] = None
    requires_prescription: Optional[bool] = None
    in_stock_only: Optional[bool] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    manufacturer: Optional[str] = None
    sort_by: Optional[str] = "name_asc"

class CreateMedicineRequest(BaseModel):
    brand: str = Field(..., min_length=1)
    generic_name: str = Field(..., min_length=1)
    strength: str = Field(..., min_length=1)
    dosage_form: str = "Tablet"
    category: MedicineCategory = MedicineCategory.TABLET
    manufacturer: str = Field(..., min_length=1)
    unit_price: float = Field(..., gt=0.0)
    pack_size: str = "10 Tablets/Strip"
    requires_prescription: bool = False
    description: Optional[str] = None
    stock_count: int = Field(100, ge=0)

class UpdateMedicineRequest(BaseModel):
    unit_price: Optional[float] = Field(None, gt=0.0)
    stock_count: Optional[int] = Field(None, ge=0)
    in_stock: Optional[bool] = None
    requires_prescription: Optional[bool] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class CategorySummaryResponse(BaseModel):
    category: str
    count: int

class MedicineDetailResponse(BaseModel):
    id: Optional[str] = None
    medicine_id: Optional[str] = None
    slug: str
    medicine_name: str
    generic_name: str
    category_name: Optional[str] = None
    category_slug: Optional[str] = None
    manufacturer_name: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    product_info: Optional[Dict[str, Any]] = None
    medicine_details: Optional[Dict[str, Any]] = None
    related_medicines: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class CrawlerSettingsModel(BaseModel):
    api_base_url: str = "https://api.medeasy.health"
    next_data_base_url: str = "https://medeasy.health"
    session_id: str = "uWWQE90f364vl5aK7aV00"
    category_slug: str = "otc-medicine"
    category_name: str = "OTC Medicine"
    rate_limit_delay_seconds: float = 0.3
    max_pages: Optional[int] = None
    updated_at: Optional[datetime] = None

class UpdateCrawlerSettingsRequest(BaseModel):
    api_base_url: Optional[str] = None
    next_data_base_url: Optional[str] = None
    session_id: Optional[str] = None
    category_slug: Optional[str] = None
    category_name: Optional[str] = None
    rate_limit_delay_seconds: Optional[float] = None
    max_pages: Optional[int] = None

class CrawlerStartRequest(BaseModel):
    category_slug: Optional[str] = "otc-medicine"
    start_page: int = 1
    max_pages: Optional[int] = None

class CrawlerJobStatusResponse(BaseModel):
    job_id: Optional[str] = None
    is_running: bool = False
    status: str = "IDLE"  # IDLE, RUNNING, COMPLETED, STOPPED, FAILED
    category_slug: str = "otc-medicine"
    current_page: int = 0
    total_pages: int = 0
    total_products_found: int = 0
    inserted_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    logs: List[str] = []

class PharmacyStatsResponse(BaseModel):
    total_medicines: int
    in_stock_medicines: int
    total_categories: int
    total_manufacturers: int
    last_crawled_at: Optional[datetime] = None
    crawler_status: str
