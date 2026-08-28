from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.common.enums import MedicineCategory

class MedicineResponse(BaseModel):
    id: str
    name: str
    brand: str
    generic_name: str
    strength: str
    dosage_form: str
    category: MedicineCategory
    manufacturer: str
    unit_price: float
    pack_size: str
    requires_prescription: bool
    description: Optional[str] = None
    in_stock: bool
    stock_count: int
    is_active: bool
    source: Optional[str] = "MedEasy"

class MedicineFilterParams(BaseModel):
    search: Optional[str] = None
    generic_name: Optional[str] = None
    category: Optional[MedicineCategory] = None
    requires_prescription: Optional[bool] = None
    in_stock_only: Optional[bool] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    manufacturer: Optional[str] = None

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

