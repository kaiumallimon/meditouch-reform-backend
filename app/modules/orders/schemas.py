from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.common.enums import OrderStatus
from app.modules.users.schemas import AddressSchema

class CartItemInput(BaseModel):
    medicine_id: str
    quantity: int = Field(..., ge=1, le=100)

class CartItemDetail(BaseModel):
    medicine_id: str
    name: str
    brand: str
    strength: str
    unit_price: float
    quantity: int
    total_price: float
    requires_prescription: bool
    in_stock: bool
    stock_count: int

class CartResponse(BaseModel):
    user_id: str
    items: List[CartItemDetail] = Field(default_factory=list)
    items_count: int = 0
    subtotal: float = 0.0
    delivery_fee: float = 0.0
    estimated_total: float = 0.0
    has_prescription_items: bool = False

class CheckoutRequest(BaseModel):
    delivery_address: AddressSchema
    prescription_urls: Optional[List[str]] = Field(default_factory=list)
    customer_notes: Optional[str] = None

class OrderItemDetail(BaseModel):
    medicine_id: str
    name: str
    brand: str
    strength: str
    unit_price: float
    quantity: int
    total_price: float

class TrackingEvent(BaseModel):
    status: OrderStatus
    note: str
    timestamp: datetime

class OrderResponse(BaseModel):
    id: str
    order_number: str
    user_id: str
    user_name: str
    user_phone: str
    items: List[OrderItemDetail]
    subtotal: float
    delivery_fee: float
    total_amount: float
    delivery_address: AddressSchema
    status: OrderStatus
    payment_id: Optional[str] = None
    merchant_invoice_number: Optional[str] = None
    payment_url: Optional[str] = None
    bkash_trx_id: Optional[str] = None
    requires_prescription: bool = False
    prescription_urls: List[str] = Field(default_factory=list)
    customer_notes: Optional[str] = None
    tracking_history: List[TrackingEvent] = Field(default_factory=list)
    created_at: Optional[datetime] = None

class UpdateOrderStatusRequest(BaseModel):
    status: OrderStatus
    tracking_note: Optional[str] = None

