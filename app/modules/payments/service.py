from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

from app.modules.payments.repository import PaymentRepository
from app.modules.payments.schemas import (
    PaymentInitiationResult,
    PaymentDetailsResponse,
    RefundPaymentResponse
)
from app.integrations.bkash.client import bkash_client
from app.common.enums import (
    PaymentStatus,
    PaymentTargetType,
    PaymentGateway,
    AppointmentStatus,
    OrderStatus,
    TimeslotStatus,
    NotificationType,
    AuditAction
)
from app.common.utils import generate_invoice_number
from app.core.exceptions import (
    NotFoundException,
    BadRequestException,
    PaymentFailedException
)
from app.core.logging import logger, log_audit_event

class PaymentService:
    def __init__(self, repo: PaymentRepository, db: AsyncIOMotorDatabase):
        self.repo = repo
        self.db = db

    async def initiate_payment(
        self,
        user_id: str,
        payer_phone: str,
        amount: float,
        target_type: PaymentTargetType,
        target_id: str,
        merchant_invoice_number: Optional[str] = None
    ) -> PaymentInitiationResult:
        if amount <= 0:
            raise BadRequestException("Payment amount must be greater than zero")

        invoice_num = merchant_invoice_number or generate_invoice_number(prefix="MT")

        bkash_res = await bkash_client.create_payment(
            payer_reference=payer_phone,
            amount=amount,
            merchant_invoice_number=invoice_num
        )

        payment_doc = {
            "id": str(uuid.uuid4()),
            "merchant_invoice_number": invoice_num,
            "user_id": user_id,
            "target_type": target_type.value if isinstance(target_type, PaymentTargetType) else target_type,
            "target_id": target_id,
            "amount": amount,
            "currency": "BDT",
            "gateway": PaymentGateway.BKASH.value,
            "status": PaymentStatus.PENDING.value,
            "bkash_payment_id": bkash_res.paymentID,
            "bkash_url": bkash_res.bkashURL,
            "raw_create_response": bkash_res.model_dump()
        }

        saved = await self.repo.create(payment_doc)

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.PAYMENT_INITIATED,
            target_type="PAYMENT",
            target_id=saved["id"],
            details={"amount": amount, "target_type": target_type.value, "target_id": target_id}
        )

        return PaymentInitiationResult(
            payment_id=saved["id"],
            merchant_invoice_number=invoice_num,
            amount=amount,
            currency="BDT",
            bkash_url=bkash_res.bkashURL,
            target_type=target_type,
            target_id=target_id,
            status=PaymentStatus.PENDING
        )

    async def process_bkash_callback(self, bkash_payment_id: str, callback_status: str) -> PaymentDetailsResponse:
        payment = await self.repo.get_by_bkash_payment_id(bkash_payment_id)
        if not payment:
            raise NotFoundException(f"Payment with bKash ID {bkash_payment_id} not found")

        # Idempotency check
        if payment.get("status") == PaymentStatus.COMPLETED.value:
            logger.info(f"Payment {payment['id']} already COMPLETED. Returning idempotent response.")
            return PaymentDetailsResponse(**payment)

        if callback_status.lower() in ["cancel", "cancelled"]:
            updated = await self.repo.update_status_atomic(payment["id"], PaymentStatus.CANCELLED)
            return PaymentDetailsResponse(**updated)

        if callback_status.lower() in ["failure", "failed"]:
            updated = await self.repo.update_status_atomic(payment["id"], PaymentStatus.FAILED)
            return PaymentDetailsResponse(**updated)

        if callback_status.lower() != "success":
            raise BadRequestException(f"Unknown callback status: {callback_status}")

        exec_res = await bkash_client.execute_payment(bkash_payment_id)
        if exec_res.transactionStatus != "Completed":
            await self.repo.update_status_atomic(
                payment["id"],
                PaymentStatus.FAILED,
                raw_response=exec_res.model_dump()
            )
            raise PaymentFailedException(f"Payment execution failed: {exec_res.statusMessage}")

        updated_payment = await self.repo.update_status_atomic(
            payment_id=payment["id"],
            status=PaymentStatus.COMPLETED,
            bkash_trx_id=exec_res.trxID,
            raw_response=exec_res.model_dump()
        )

        target_type = payment.get("target_type")
        if target_type == PaymentTargetType.APPOINTMENT.value:
            await self._on_appointment_payment_success(payment, exec_res.trxID)
        elif target_type == PaymentTargetType.PHARMACY_ORDER.value:
            await self._on_order_payment_success(payment, exec_res.trxID)

        await log_audit_event(
            self.db,
            user_id=payment.get("user_id"),
            action=AuditAction.PAYMENT_COMPLETED,
            target_type="PAYMENT",
            target_id=payment["id"],
            details={"trx_id": exec_res.trxID, "amount": payment["amount"]}
        )

        return PaymentDetailsResponse(**updated_payment)

    async def _on_appointment_payment_success(self, payment: Dict[str, Any], trx_id: Optional[str]) -> None:
        appointment_id = payment.get("target_id")
        appointment = await self.db.appointments.find_one({"id": appointment_id})
        if not appointment:
            logger.error(f"Appointment {appointment_id} not found on payment success")
            return

        await self.db.appointments.update_one(
            {"id": appointment_id},
            {"$set": {
                "status": AppointmentStatus.CONFIRMED.value,
                "payment_id": payment["id"],
                "bkash_trx_id": trx_id,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        if appointment.get("timeslot_id"):
            await self.db.timeslots.update_one(
                {"id": appointment["timeslot_id"]},
                {"$set": {
                    "status": TimeslotStatus.BOOKED.value,
                    "updated_at": datetime.now(timezone.utc)
                }}
            )

        if appointment.get("doctor_id"):
            await self.db.doctors.update_one(
                {"id": appointment["doctor_id"]},
                {"$inc": {"total_consultations": 1}}
            )

        patient_user_id = appointment.get("patient_id")
        doctor_doc = await self.db.doctors.find_one({"id": appointment.get("doctor_id")})
        doctor_user_id = doctor_doc.get("user_id") if doctor_doc else None

        if patient_user_id:
            await self.db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": patient_user_id,
                "type": NotificationType.APPOINTMENT_CONFIRMED.value,
                "title": "Appointment Confirmed",
                "message": f"Your appointment with Dr. {appointment.get('doctor_name')} is confirmed for {appointment.get('start_time')}.",
                "payload": {"appointment_id": appointment_id},
                "is_read": False,
                "created_at": datetime.now(timezone.utc)
            })

        if doctor_user_id:
            await self.db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": doctor_user_id,
                "type": NotificationType.APPOINTMENT_CONFIRMED.value,
                "title": "New Confirmed Appointment",
                "message": f"New consultation booked by {appointment.get('patient_name')} for {appointment.get('start_time')}.",
                "payload": {"appointment_id": appointment_id},
                "is_read": False,
                "created_at": datetime.now(timezone.utc)
            })

    async def _on_order_payment_success(self, payment: Dict[str, Any], trx_id: Optional[str]) -> None:
        order_id = payment.get("target_id")
        order = await self.db.orders.find_one({"id": order_id})
        if not order:
            logger.error(f"Order {order_id} not found on payment success")
            return

        for item in order.get("items", []):
            med_id = item.get("medicine_id")
            qty = item.get("quantity", 1)
            await self.db.medicines.update_one(
                {"id": med_id, "stock_count": {"$gte": qty}},
                {
                    "$inc": {"stock_count": -qty},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )

        await self.db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "status": OrderStatus.CONFIRMED.value,
                "payment_id": payment["id"],
                "bkash_trx_id": trx_id,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        user_id = order.get("user_id")
        if user_id:
            await self.db.carts.delete_one({"user_id": user_id})
            await self.db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "type": NotificationType.ORDER_CONFIRMED.value,
                "title": "Order Confirmed",
                "message": f"Your medicine order #{order.get('order_number', order_id)} of BDT {order.get('total_amount')} has been confirmed.",
                "payload": {"order_id": order_id},
                "is_read": False,
                "created_at": datetime.now(timezone.utc)
            })

    async def get_payment_details(self, payment_id: str) -> PaymentDetailsResponse:
        payment = await self.repo.get_by_id(payment_id)
        if not payment:
            raise NotFoundException("Payment record not found")
        return PaymentDetailsResponse(**payment)

    async def refund_payment(self, payment_id: str, reason: str, user_id: str) -> RefundPaymentResponse:
        payment = await self.repo.get_by_id(payment_id)
        if not payment:
            raise NotFoundException("Payment record not found")

        if payment.get("status") != PaymentStatus.COMPLETED.value:
            raise BadRequestException("Only COMPLETED payments can be refunded")

        bkash_payment_id = payment.get("bkash_payment_id")
        trx_id = payment.get("bkash_trx_id")
        amount = payment.get("amount", 0.0)

        refund_res = await bkash_client.refund_payment(
            payment_id=bkash_payment_id,
            trx_id=trx_id or "",
            amount=amount,
            reason=reason
        )

        now = datetime.now(timezone.utc)
        await self.repo.update_status_atomic(
            payment_id=payment_id,
            status=PaymentStatus.REFUNDED,
            raw_response=refund_res.model_dump()
        )

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.PAYMENT_REFUNDED,
            target_type="PAYMENT",
            target_id=payment_id,
            details={"refund_trx_id": refund_res.refundTrxID, "reason": reason, "amount": amount}
        )

        return RefundPaymentResponse(
            payment_id=payment_id,
            refund_trx_id=refund_res.refundTrxID or "MOCK_REFUND",
            original_trx_id=trx_id or "",
            amount=amount,
            status=PaymentStatus.REFUNDED,
            refunded_at=now
        )

