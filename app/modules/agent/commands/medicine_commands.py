from pydantic import BaseModel, Field
from typing import Optional
from app.common.enums import MedicineCategory

class CreateMedicineCommand(BaseModel):
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

class UpdateMedicineCommand(BaseModel):
    medicine_id: str = Field(..., min_length=1)
    unit_price: Optional[float] = Field(None, gt=0.0)
    stock_count: Optional[int] = Field(None, ge=0)
    in_stock: Optional[bool] = None
    requires_prescription: Optional[bool] = None
    description: Optional[str] = None

class DeleteMedicineCommand(BaseModel):
    medicine_id_or_slug: str = Field(..., min_length=1)
    reason: Optional[str] = "Catalog item removed via Admin AI Assistant"
