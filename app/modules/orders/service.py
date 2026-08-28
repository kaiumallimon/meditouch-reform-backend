from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid

from app.modules.orders.repository import OrderRepository
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.payments.service import PaymentService
from app.modules.orders.schemas import (
    CartItemInput,
    CartItemDetail,
    CartResponse,
    CheckoutRequest,
    OrderItemDetail,
    OrderResponse,
    TrackingEvent,
    UpdateOrderStatusRequest
)
from app.common.enums import (
    OrderStatus,
    PaymentTargetType,
    UserRole,
    NotificationType,
    AuditAction
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.utils import generate_invoice_number
from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    BadRequestException,
    ForbiddenException,
    OutOfStockException
)
from app.core.logging import log_audit_event

class OrderService:
    def __init__(
        self,
        repo: OrderRepository,
        pharmacy_repo: PharmacyRepository,
        payment_service: PaymentService,
        db: AsyncIOMotorDatabase
    ):
        self.repo = repo
        self.pharmacy_repo = pharmacy_repo
        self.payment_service = payment_service
        self.db = db

    # 1. Cart Operations
    async def get_cart(self, user_id: str) -> CartResponse:
        cart = await self.repo.get_cart_by_user_id(user_id)
        raw_items = cart.get("items", []) if cart else []

        detailed_items: List[CartItemDetail] = []
        subtotal = 0.0
        has_prescription = False

        for item in raw_items:
            med_id = item.get("medicine_id")
            qty = item.get("quantity", 1)
            med = await self.pharmacy_repo.get_by_id(med_id)
            if not med or not med.get("is_active", True):
                continue

            unit_price = float(med.get("unit_price", 0.0))
            item_total = round(unit_price * qty, 2)
            subtotal += item_total

            req_presc = bool(med.get("requires_prescription", False))
            if req_presc:
                has_prescription = True

            stock_count = int(med.get("stock_count", 0))

            detailed_items.append(
                CartItemDetail(
                    medicine_id=med_id,
                    name=med.get("name", "Medicine"),
                    brand=med.get("brand", ""),
                    strength=med.get("strength", ""),
                    unit_price=unit_price,
                    quantity=qty,
                    total_price=item_total,
                    requires_prescription=req_presc,
                    in_stock=stock_count >= qty,
                    stock_count=stock_count
                )
            )

        delivery_fee = settings.PLATFORM_DELIVERY_FEE_BDT if detailed_items else 0.0
        estimated_total = round(subtotal + delivery_fee, 2)

        return CartResponse(
            user_id=user_id,
            items=detailed_items,
            items_count=len(detailed_items),
            subtotal=round(subtotal, 2),
            delivery_fee=delivery_fee,
            estimated_total=estimated_total,
            has_prescription_items=has_prescription
        )

    async def update_cart_item(self, user_id: str, item_in: CartItemInput) -> CartResponse:
        med = await self.pharmacy_repo.get_by_id(item_in.medicine_id)
        if not med or not med.get("is_active", True):
            raise NotFoundException("Medicine not found")

        cart = await self.repo.get_cart_by_user_id(user_id)
        raw_items = cart.get("items", []) if cart else []

        found = False
        new_items = []
        for it in raw_items:
            if it.get("medicine_id") == item_in.medicine_id:
                new_items.append({"medicine_id": item_in.medicine_id, "quantity": item_in.quantity})
                found = True
            else:
                new_items.append(it)

        if not found:
            new_items.append({"medicine_id": item_in.medicine_id, "quantity": item_in.quantity})

        await self.repo.save_cart(user_id, new_items)
        return await self.get_cart(user_id)

    async def remove_cart_item(self, user_id: str, medicine_id: str) -> CartResponse:
        cart = await self.repo.get_cart_by_user_id(user_id)
        raw_items = cart.get("items", []) if cart else []
        new_items = [it for it in raw_items if it.get("medicine_id") != medicine_id]
        await self.repo.save_cart(user_id, new_items)
        return await self.get_cart(user_id)

    async def clear_cart(self, user_id: str) -> CartResponse:
        await self.repo.clear_cart(user_id)
        return await self.get_cart(user_id)

    # 2. Checkout & Order Placement
    async def checkout(self, user_id: str, req: CheckoutRequest) -> OrderResponse:
        user = await self.db.users.find_one({"id": user_id})
        if not user:
            raise NotFoundException("User not found")

        cart = await self.get_cart(user_id)
        if not cart.items:
            raise BadRequestException("Your cart is empty")

        order_items: List[OrderItemDetail] = []
        for item in cart.items:
            if not item.in_stock or item.stock_count < item.quantity:
                raise OutOfStockException(
                    f"'{item.name}' is out of stock or insufficient quantity (Available: {item.stock_count}, Requested: {item.quantity})"
                )

            order_items.append(
                OrderItemDetail(
                    medicine_id=item.medicine_id,
                    name=item.name,
                    brand=item.brand,
                    strength=item.strength,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                    total_price=item.total_price
                )
            )

        if cart.has_prescription_items and not req.prescription_urls:
            raise BadRequestException(
                "One or more items in your cart require a doctor's prescription. Please upload prescription images."
            )

        order_number = generate_invoice_number(prefix="ORD")
        subtotal = cart.subtotal
        delivery_fee = settings.PLATFORM_DELIVERY_FEE_BDT
        total_amount = round(subtotal + delivery_fee, 2)

        now = datetime.now(timezone.utc)
        initial_tracking = [
            {
                "status": OrderStatus.PENDING_PAYMENT.value,
                "note": "Order placed. Awaiting bKash payment verification.",
                "timestamp": now
            }
        ]

        order_doc = {
            "order_number": order_number,
            "user_id": user_id,
            "user_name": user.get("name", "Customer"),
            "user_phone": user.get("phone", ""),
            "items": [it.model_dump() for it in order_items],
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "total_amount": total_amount,
            "delivery_address": req.delivery_address.model_dump(),
            "status": OrderStatus.PENDING_PAYMENT.value,
            "merchant_invoice_number": order_number,
            "requires_prescription": cart.has_prescription_items,
            "prescription_urls": req.prescription_urls or [],
            "customer_notes": req.customer_notes,
            "tracking_history": initial_tracking,
            "created_at": now
        }

        created = await self.repo.create_order(order_doc)

        try:
            payment_res = await self.payment_service.initiate_payment(
                user_id=user_id,
                payer_phone=req.delivery_address.recipient_phone or user.get("phone", "01700000000"),
                amount=total_amount,
                target_type=PaymentTargetType.PHARMACY_ORDER,
                target_id=created["id"],
                merchant_invoice_number=order_number
            )

            await self.db.orders.update_one(
                {"id": created["id"]},
                {"$set": {"payment_id": payment_res.payment_id, "payment_url": payment_res.bkash_url}}
            )
            created["payment_id"] = payment_res.payment_id
            created["payment_url"] = payment_res.bkash_url
        except Exception as e:
            await self.repo.update_order_status(created["id"], OrderStatus.CANCELLED, "Payment gateway initialization failed")
            raise BadRequestException(f"Payment gateway error: {str(e)}")

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.ORDER_PLACED,
            target_type="ORDER",
            target_id=created["id"],
            details={"total_amount": total_amount, "items_count": len(order_items)}
        )

        return self._format_order_response(created)

    async def get_user_orders(
        self,
        user_id: str,
        status: Optional[OrderStatus],
        pagination: PaginationParams
    ) -> PaginatedResponse[OrderResponse]:
        docs, total = await self.repo.get_user_orders(
            user_id=user_id,
            status=status,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [self._format_order_response(d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_all_orders_admin(
        self,
        status: Optional[OrderStatus],
        pagination: PaginationParams
    ) -> PaginatedResponse[OrderResponse]:
        docs, total = await self.repo.get_all_orders(
            status=status,
            skip=pagination.skip,
            limit=pagination.limit
        )
        items = [self._format_order_response(d) for d in docs]
        return PaginatedResponse.create(items=items, total=total, params=pagination)

    async def get_order_by_id(
        self,
        order_id: str,
        user_id: str,
        user_role: str
    ) -> OrderResponse:
        order = await self.repo.get_order_by_id(order_id)
        if not order:
            raise NotFoundException("Order not found")

        if user_role != UserRole.ADMIN.value and order.get("user_id") != user_id:
            raise ForbiddenException("You are not authorized to view this order")

        return self._format_order_response(order)

    async def update_order_status(
        self,
        order_id: str,
        req: UpdateOrderStatusRequest,
        admin_id: str
    ) -> OrderResponse:
        order = await self.repo.get_order_by_id(order_id)
        if not order:
            raise NotFoundException("Order not found")

        updated = await self.repo.update_order_status(
            order_id=order_id,
            new_status=req.status,
            tracking_note=req.tracking_note
        )

        await self.db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": order["user_id"],
            "type": NotificationType.ORDER_STATUS_UPDATE.value,
            "title": f"Order #{order.get('order_number')} Updated",
            "message": f"Your order status is now: {req.status.value}. {req.tracking_note or ''}",
            "payload": {"order_id": order_id, "new_status": req.status.value},
            "is_read": False,
            "created_at": datetime.now(timezone.utc)
        })

        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.ORDER_STATUS_CHANGED,
            target_type="ORDER",
            target_id=order_id,
            details={"new_status": req.status.value, "note": req.tracking_note}
        )

        return self._format_order_response(updated)

    def _format_order_response(self, order: Dict[str, Any]) -> OrderResponse:
        return OrderResponse(
            id=order["id"],
            order_number=order.get("order_number", order["id"]),
            user_id=order["user_id"],
            user_name=order.get("user_name", ""),
            user_phone=order.get("user_phone", ""),
            items=[OrderItemDetail(**it) for it in order.get("items", [])],
            subtotal=order.get("subtotal", 0.0),
            delivery_fee=order.get("delivery_fee", 0.0),
            total_amount=order.get("total_amount", 0.0),
            delivery_address=order.get("delivery_address", {}),
            status=OrderStatus(order.get("status")),
            payment_id=order.get("payment_id"),
            merchant_invoice_number=order.get("merchant_invoice_number"),
            payment_url=order.get("payment_url"),
            bkash_trx_id=order.get("bkash_trx_id"),
            requires_prescription=order.get("requires_prescription", False),
            prescription_urls=order.get("prescription_urls", []),
            customer_notes=order.get("customer_notes"),
            tracking_history=[TrackingEvent(**tr) for tr in order.get("tracking_history", [])],
            created_at=order.get("created_at")
        )

