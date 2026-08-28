from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.common.enums import PaymentStatus, PaymentTargetType, PaymentGateway

class PaymentInitiationResult(BaseModel):
    payment_id: str
    merchant_invoice_number: str
    amount: float
    currency: str = "BDT"
    bkash_url: str
    target_type: PaymentTargetType
    target_id: str
    status: PaymentStatus

class PaymentCallbackRequest(BaseModel):
    paymentID: str
    status: str

class PaymentDetailsResponse(BaseModel):
    id: str
    merchant_invoice_number: str
    user_id: str
    target_type: PaymentTargetType
    target_id: str
    amount: float
    currency: str
    gateway: PaymentGateway
    status: PaymentStatus
    bkash_payment_id: Optional[str] = None
    bkash_trx_id: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class RefundPaymentRequest(BaseModel):
    reason: str = "Customer cancellation"

class RefundPaymentResponse(BaseModel):
    payment_id: str
    refund_trx_id: str
    original_trx_id: str
    amount: float
    status: PaymentStatus
    refunded_at: datetime

