from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
from app.common.enums import PaymentStatus

class PaymentRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_by_id(self, payment_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.payments.find_one({"id": payment_id})

    async def get_by_invoice(self, merchant_invoice_number: str) -> Optional[Dict[str, Any]]:
        return await self.db.payments.find_one({"merchant_invoice_number": merchant_invoice_number})

    async def get_by_bkash_payment_id(self, bkash_payment_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.payments.find_one({"bkash_payment_id": bkash_payment_id})

    async def create(self, payment_doc: Dict[str, Any]) -> Dict[str, Any]:
        if "id" not in payment_doc:
            payment_doc["id"] = str(uuid.uuid4())
        if "created_at" not in payment_doc:
            payment_doc["created_at"] = datetime.now(timezone.utc)
        payment_doc["updated_at"] = datetime.now(timezone.utc)
        await self.db.payments.insert_one(payment_doc)
        return payment_doc

    async def update_status_atomic(
        self,
        payment_id: str,
        status: PaymentStatus,
        bkash_trx_id: Optional[str] = None,
        raw_response: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        updates: Dict[str, Any] = {
            "status": status.value if isinstance(status, PaymentStatus) else status,
            "updated_at": datetime.now(timezone.utc)
        }
        if status == PaymentStatus.COMPLETED:
            updates["completed_at"] = datetime.now(timezone.utc)
        if bkash_trx_id:
            updates["bkash_trx_id"] = bkash_trx_id
        if raw_response:
            updates["raw_response"] = raw_response

        return await self.db.payments.find_one_and_update(
            {"id": payment_id},
            {"$set": updates},
            return_document=True
        )

