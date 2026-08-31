from typing import List, Optional, Dict, Any, AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from datetime import datetime, timezone
import asyncio
import json
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
from app.core.logging import log_audit_event, logger

class OrderEventBroadcaster:
    """Singleton in-memory PubSub for real-time SSE streaming to Admin Dashboards."""
    _instance: Optional["OrderEventBroadcaster"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OrderEventBroadcaster, cls).__new__(cls)
            cls._instance._subscribers = set()
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        async with self._lock:
            self._subscribers.discard(queue)

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        async with self._lock:
            dead_queues = set()
            for queue in self._subscribers:
                try:
                    queue.put_nowait({"event": event_type, "data": data, "timestamp": datetime.now(timezone.utc).isoformat()})
                except asyncio.QueueFull:
                    dead_queues.add(queue)
                except Exception:
                    dead_queues.add(queue)
            for q in dead_queues:
                self._subscribers.discard(q)

order_broadcaster = OrderEventBroadcaster()
_checkout_mutex = asyncio.Lock()

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

    # 2. Checkout & Order Placement with Atomic Stock Reservation & Queue Lock
    async def checkout(self, user_id: str, req: CheckoutRequest) -> OrderResponse:
        user = await self.db.users.find_one({"id": user_id})
        if not user:
            raise NotFoundException("User not found")

        cart = await self.get_cart(user_id)
        if not cart.items:
            raise BadRequestException("Your cart is empty")

        if cart.has_prescription_items and not req.prescription_urls:
            raise BadRequestException(
                "One or more items in your cart require a doctor's prescription. Please upload prescription images."
            )

        # Concurrency & Race-Condition Safe Stock Reservation
        decremented_items: List[tuple[str, int]] = []
        order_items: List[OrderItemDetail] = []

        async with _checkout_mutex:
            try:
                for item in cart.items:
                    # Atomic conditional decrement
                    updated_med = await self.db.medicines.find_one_and_update(
                        {"id": item.medicine_id, "stock_count": {"$gte": item.quantity}},
                        {"$inc": {"stock_count": -item.quantity}},
                        return_document=ReturnDocument.AFTER
                    )

                    if not updated_med:
                        # Fetch current remaining stock for a helpful message
                        current_med = await self.db.medicines.find_one({"id": item.medicine_id})
                        available = current_med.get("stock_count", 0) if current_med else 0
                        raise OutOfStockException(
                            f"'{item.name}' is out of stock or has insufficient available quantity (Available: {available}, Requested: {item.quantity}). Please adjust your cart."
                        )

                    decremented_items.append((item.medicine_id, item.quantity))

                    # Update in_stock flag if zero
                    if updated_med.get("stock_count", 0) <= 0:
                        await self.db.medicines.update_one(
                            {"id": item.medicine_id},
                            {"$set": {"in_stock": False}}
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
            except Exception as ex:
                # Compensation Rollback: Restore any items decremented before failure
                for med_id, qty in decremented_items:
                    await self.db.medicines.update_one(
                        {"id": med_id},
                        {"$inc": {"stock_count": qty}, "$set": {"in_stock": True}}
                    )
                raise ex

        order_number = generate_invoice_number(prefix="ORD")
        subtotal = cart.subtotal
        delivery_fee = settings.PLATFORM_DELIVERY_FEE_BDT
        total_amount = round(subtotal + delivery_fee, 2)

        now = datetime.now(timezone.utc)
        initial_tracking = [
            {
                "status": OrderStatus.CONFIRMED.value,
                "note": "Order placed and confirmed. Items reserved from pharmacy inventory.",
                "timestamp": now
            }
        ]

        delivery_addr_dict = req.delivery_address.model_dump()
        if not delivery_addr_dict.get("id"):
            delivery_addr_dict["id"] = str(uuid.uuid4())

        order_doc = {
            "order_number": order_number,
            "user_id": user_id,
            "user_name": user.get("name", req.delivery_address.recipient_name or "Customer"),
            "user_phone": req.delivery_address.recipient_phone or user.get("phone", ""),
            "items": [it.model_dump() for it in order_items],
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "total_amount": total_amount,
            "delivery_address": delivery_addr_dict,
            "status": OrderStatus.CONFIRMED.value, # CONFIRMED is default as per directive
            "merchant_invoice_number": order_number,
            "requires_prescription": cart.has_prescription_items,
            "prescription_urls": req.prescription_urls or [],
            "customer_notes": req.customer_notes,
            "tracking_history": initial_tracking,
            "created_at": now,
            "updated_at": now
        }

        created = await self.repo.create_order(order_doc)

        # Clear cart on successful order placement
        await self.repo.clear_cart(user_id)

        # Auto-save delivery address if not already present in user's saved addresses
        try:
            existing_addrs = user.get("addresses", [])
            already_saved = any(
                a.get("street_address") == delivery_addr_dict.get("street_address") and
                a.get("district") == delivery_addr_dict.get("district")
                for a in existing_addrs
            )
            if not already_saved:
                await self.db.users.update_one(
                    {"id": user_id},
                    {"$push": {"addresses": delivery_addr_dict}}
                )
        except Exception as e:
            logger.warning(f"Failed to auto-save checkout address to user profile: {e}")

        # Log audit event
        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.ORDER_PLACED,
            target_type="ORDER",
            target_id=created["id"],
            details={"total_amount": total_amount, "items_count": len(order_items), "order_number": order_number}
        )

        formatted = self._format_order_response(created)

        # Broadcast new order to Admin Real-Time SSE Stream
        await order_broadcaster.broadcast(
            "order_created",
            formatted.model_dump(mode="json")
        )

        return formatted

    # 3. User Order Cancellation with Stock Restoration
    async def cancel_order(
        self,
        order_id: str,
        user_id: str,
        user_role: str,
        reason: Optional[str] = None
    ) -> OrderResponse:
        order = await self.repo.get_order_by_id(order_id)
        if not order:
            raise NotFoundException("Order not found")

        # Authorization: user can only cancel their own order, ADMIN can cancel any
        if user_role != UserRole.ADMIN.value and order.get("user_id") != user_id:
            raise ForbiddenException("You are not authorized to cancel this order")

        current_status = order.get("status")

        # Cancellation Rule: Only permitted when status is CONFIRMED or PROCESSING (below SHIPPED)
        if current_status in [OrderStatus.SHIPPED.value, OrderStatus.DELIVERED.value]:
            raise BadRequestException(
                f"Order #{order.get('order_number')} cannot be cancelled because it is already {current_status}. Please contact support."
            )

        if current_status == OrderStatus.CANCELLED.value:
            raise BadRequestException("Order is already cancelled")

        cancel_note = reason or ("Cancelled by customer" if user_role != UserRole.ADMIN.value else "Cancelled by administration")

        # Atomically update status
        updated = await self.repo.update_order_status(
            order_id=order_id,
            new_status=OrderStatus.CANCELLED,
            tracking_note=cancel_note
        )

        # Atomically restore stock in pharmacy inventory
        for it in order.get("items", []):
            med_id = it.get("medicine_id")
            qty = it.get("quantity", 0)
            if med_id and qty > 0:
                await self.db.medicines.update_one(
                    {"id": med_id},
                    {"$inc": {"stock_count": qty}, "$set": {"in_stock": True}}
                )

        # Send in-app notification
        await self.db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": order["user_id"],
            "type": NotificationType.ORDER_STATUS_UPDATE.value,
            "title": f"Order #{order.get('order_number')} Cancelled",
            "message": f"Your order has been cancelled: {cancel_note}",
            "payload": {"order_id": order_id, "status": OrderStatus.CANCELLED.value},
            "is_read": False,
            "created_at": datetime.now(timezone.utc)
        })

        # Log audit event
        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.ORDER_STATUS_CHANGED,
            target_type="ORDER",
            target_id=order_id,
            details={"status": OrderStatus.CANCELLED.value, "reason": cancel_note}
        )

        formatted = self._format_order_response(updated)

        # Broadcast update to Admin Real-Time SSE Stream
        await order_broadcaster.broadcast(
            "order_cancelled",
            formatted.model_dump(mode="json")
        )

        return formatted

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

        old_status = order.get("status")
        new_status = req.status.value

        # If transitioning to CANCELLED, restore stock
        if req.status == OrderStatus.CANCELLED and old_status != OrderStatus.CANCELLED.value:
            for it in order.get("items", []):
                med_id = it.get("medicine_id")
                qty = it.get("quantity", 0)
                if med_id and qty > 0:
                    await self.db.medicines.update_one(
                        {"id": med_id},
                        {"$inc": {"stock_count": qty}, "$set": {"in_stock": True}}
                    )

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
            details={"old_status": old_status, "new_status": req.status.value, "note": req.tracking_note}
        )

        formatted = self._format_order_response(updated)

        # Broadcast status update to Admin Real-Time SSE Stream
        await order_broadcaster.broadcast(
            "order_updated",
            formatted.model_dump(mode="json")
        )

        return formatted

    async def get_orders_stream(self) -> AsyncGenerator[str, None]:
        """Real-time SSE event stream for admin order dashboard."""
        queue = await order_broadcaster.subscribe()
        try:
            # Yield initial connection confirmation
            yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
            while True:
                try:
                    # Timeout for heartbeat ping every 15s
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
        finally:
            await order_broadcaster.unsubscribe(queue)

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

