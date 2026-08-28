from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.payments.repository import PaymentRepository
from app.modules.payments.service import PaymentService
from app.modules.payments.schemas import (
    PaymentDetailsResponse,
    RefundPaymentRequest,
    RefundPaymentResponse
)
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload
from app.common.enums import UserRole
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/payments", tags=["Payments & bKash"])

def get_payment_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> PaymentService:
    repo = PaymentRepository(db)
    return PaymentService(repo, db)

@router.get("/bkash/callback", response_model=APIResponse[PaymentDetailsResponse])
async def bkash_callback_get(
    paymentID: str = Query(..., description="bKash Payment ID"),
    status: str = Query(..., description="Callback status: success, failure, cancel"),
    service: PaymentService = Depends(get_payment_service)
):
    payment_details = await service.process_bkash_callback(paymentID, status)
    return APIResponse(
        success=payment_details.status == "COMPLETED",
        message=f"Payment status: {payment_details.status}",
        data=payment_details
    )

@router.post("/bkash/callback", response_model=APIResponse[PaymentDetailsResponse])
async def bkash_callback_post(
    paymentID: str = Query(..., description="bKash Payment ID"),
    status: str = Query(..., description="Callback status: success, failure, cancel"),
    service: PaymentService = Depends(get_payment_service)
):
    payment_details = await service.process_bkash_callback(paymentID, status)
    return APIResponse(
        success=payment_details.status == "COMPLETED",
        message=f"Payment status: {payment_details.status}",
        data=payment_details
    )

@router.get("/{payment_id}", response_model=APIResponse[PaymentDetailsResponse])
async def get_payment(
    payment_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: PaymentService = Depends(get_payment_service)
):
    payment = await service.get_payment_details(payment_id)
    if payload.get("role") != UserRole.ADMIN.value and payment.user_id != payload.get("sub"):
        raise ForbiddenException("You are not authorized to view this payment record")
    return APIResponse(success=True, message="Payment retrieved", data=payment)

@router.post("/{payment_id}/refund", response_model=APIResponse[RefundPaymentResponse])
async def refund_payment(
    payment_id: str,
    req: RefundPaymentRequest,
    payload: dict = Depends(get_current_user_payload),
    service: PaymentService = Depends(get_payment_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can initiate payment refunds")
    refund_res = await service.refund_payment(payment_id, req.reason, payload["sub"])
    return APIResponse(success=True, message="Payment refunded successfully", data=refund_res)

