from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.orders.repository import OrderRepository
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.payments.repository import PaymentRepository
from app.modules.payments.service import PaymentService
from app.modules.orders.service import OrderService
from app.modules.orders.schemas import (
    CartItemInput,
    CartResponse,
    CheckoutRequest,
    OrderResponse,
    UpdateOrderStatusRequest,
    CancelOrderRequest
)
from app.common.pagination import PaginationParams, PaginatedResponse
from app.common.responses import APIResponse
from app.common.enums import OrderStatus, UserRole
from app.core.security import get_current_user_payload
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/orders", tags=["E-Pharmacy Orders & Cart"])

def get_order_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> OrderService:
    order_repo = OrderRepository(db)
    pharm_repo = PharmacyRepository(db)
    pay_repo = PaymentRepository(db)
    pay_service = PaymentService(pay_repo, db)
    return OrderService(order_repo, pharm_repo, pay_service, db)

@router.get("/cart", response_model=APIResponse[CartResponse])
async def get_my_cart(
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    cart = await service.get_cart(payload["sub"])
    return APIResponse(success=True, message="Cart retrieved", data=cart)

@router.post("/cart/items", response_model=APIResponse[CartResponse])
async def add_or_update_cart_item(
    item: CartItemInput,
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    cart = await service.update_cart_item(payload["sub"], item)
    return APIResponse(success=True, message="Cart updated", data=cart)

@router.delete("/cart/items/{medicine_id}", response_model=APIResponse[CartResponse])
async def remove_cart_item(
    medicine_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    cart = await service.remove_cart_item(payload["sub"], medicine_id)
    return APIResponse(success=True, message="Item removed from cart", data=cart)

@router.delete("/cart", response_model=APIResponse[CartResponse])
async def clear_cart(
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    cart = await service.clear_cart(payload["sub"])
    return APIResponse(success=True, message="Cart cleared", data=cart)

@router.post("/checkout", response_model=APIResponse[OrderResponse], status_code=status.HTTP_201_CREATED)
async def checkout_order(
    req: CheckoutRequest,
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    order = await service.checkout(payload["sub"], req)
    return APIResponse(success=True, message="Order confirmed and placed successfully", data=order)

@router.get("/my-orders", response_model=APIResponse[PaginatedResponse[OrderResponse]])
async def get_my_orders(
    status: Optional[OrderStatus] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    pagination = PaginationParams(page=page, limit=limit)
    orders = await service.get_user_orders(payload["sub"], status, pagination)
    return APIResponse(success=True, message="My orders retrieved", data=orders)

@router.get("/admin/stream")
async def stream_admin_orders(
    service: OrderService = Depends(get_order_service)
):
    """Real-time SSE event stream for admin order dashboard."""
    generator = await service.get_orders_stream()
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@router.get("/admin/all", response_model=APIResponse[PaginatedResponse[OrderResponse]])
async def get_all_orders_admin(
    status: Optional[OrderStatus] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can view all orders")
    pagination = PaginationParams(page=page, limit=limit)
    orders = await service.get_all_orders_admin(status, pagination)
    return APIResponse(success=True, message="All orders retrieved", data=orders)

@router.get("/{order_id}", response_model=APIResponse[OrderResponse])
async def get_order_details(
    order_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    order = await service.get_order_by_id(order_id, payload["sub"], payload.get("role", ""))
    return APIResponse(success=True, message="Order details retrieved", data=order)

@router.post("/{order_id}/cancel", response_model=APIResponse[OrderResponse])
async def cancel_order(
    order_id: str,
    req: Optional[CancelOrderRequest] = None,
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    reason = req.reason if req else "Cancelled by customer"
    order = await service.cancel_order(
        order_id=order_id,
        user_id=payload["sub"],
        user_role=payload.get("role", ""),
        reason=reason
    )
    return APIResponse(success=True, message="Order cancelled successfully and stock restored", data=order)

@router.put("/{order_id}/status", response_model=APIResponse[OrderResponse])
async def update_order_status(
    order_id: str,
    req: UpdateOrderStatusRequest,
    payload: dict = Depends(get_current_user_payload),
    service: OrderService = Depends(get_order_service)
):
    if payload.get("role") != UserRole.ADMIN.value:
        raise ForbiddenException("Only ADMIN can update order dispatch status")
    order = await service.update_order_status(order_id, req, payload["sub"])
    return APIResponse(success=True, message="Order status updated", data=order)

