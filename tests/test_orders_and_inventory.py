import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.modules.orders.service import OrderService, OrderEventBroadcaster
from app.modules.orders.schemas import (
    CheckoutRequest,
    CartItemInput,
    UpdateOrderStatusRequest,
    CancelOrderRequest
)
from app.modules.users.schemas import AddressSchema
from app.common.enums import OrderStatus, UserRole
from app.core.exceptions import OutOfStockException, BadRequestException, ForbiddenException

@pytest.mark.asyncio
async def test_atomic_stock_reservation_race_condition():
    mock_db = MagicMock()
    mock_order_repo = AsyncMock()
    mock_pharm_repo = AsyncMock()
    mock_pay_service = AsyncMock()

    service = OrderService(mock_order_repo, mock_pharm_repo, mock_pay_service, mock_db)

    stock_state = {'med_1': 105}

    async def mock_find_one_and_update(filter_dict, update_dict, return_document=None):
        med_id = filter_dict.get('id')
        min_stock = filter_dict.get('stock_count', {}).get('', 0)
        inc_val = update_dict.get('', {}).get('stock_count', 0)

        current = stock_state.get(med_id, 0)
        if current >= min_stock:
            stock_state[med_id] = current + inc_val
            return {'id': med_id, 'stock_count': stock_state[med_id]}
        return None

    mock_db.medicines.find_one_and_update.side_effect = mock_find_one_and_update
    mock_db.medicines.find_one.side_effect = lambda filter_dict: {'id': filter_dict.get('id'), 'stock_count': stock_state.get(filter_dict.get('id'), 0)}
    mock_db.medicines.update_one = AsyncMock()
    mock_db.users.find_one = AsyncMock(return_value={'id': 'user_1', 'name': 'Person A', 'phone': '01711111111', 'addresses': []})
    mock_db.users.update_one = AsyncMock()
    mock_db.audit_logs.insert_one = AsyncMock()
    mock_order_repo.create_order.side_effect = lambda doc: {**doc, 'id': 'order_123'}
    mock_order_repo.clear_cart = AsyncMock()

    mock_pharm_repo.get_by_id.return_value = {
        'id': 'med_1',
        'name': 'Napa Extra',
        'brand': 'Napa',
        'strength': '500mg',
        'unit_price': 2.5,
        'is_active': True,
        'stock_count': 105,
        'requires_prescription': False
    }
    mock_order_repo.get_cart_by_user_id.return_value = {
        'items': [{'medicine_id': 'med_1', 'quantity': 100}]
    }

    req_a = CheckoutRequest(
        delivery_address=AddressSchema(
            recipient_name='Person A',
            recipient_phone='01711111111',
            division='Dhaka',
            district='Dhaka',
            upazila_or_thana='Dhanmondi',
            street_address='House 12, Road 5'
        )
    )

    res_a = await service.checkout('user_1', req_a)
    assert res_a.status == OrderStatus.CONFIRMED
    assert stock_state['med_1'] == 5

    mock_db.users.find_one = AsyncMock(return_value={'id': 'user_2', 'name': 'Person B', 'phone': '01722222222', 'addresses': []})
    mock_order_repo.get_cart_by_user_id.return_value = {
        'items': [{'medicine_id': 'med_1', 'quantity': 10}]
    }
    req_b = CheckoutRequest(
        delivery_address=AddressSchema(
            recipient_name='Person B',
            recipient_phone='01722222222',
            division='Dhaka',
            district='Dhaka',
            upazila_or_thana='Gulshan',
            street_address='House 45, Road 11'
        )
    )

    with pytest.raises(OutOfStockException) as exc_info:
        await service.checkout('user_2', req_b)

    assert 'out of stock or has insufficient available quantity' in str(exc_info.value)
    assert stock_state['med_1'] == 5

@pytest.mark.asyncio
async def test_order_cancellation_lifecycle_and_stock_restoration():
    mock_db = MagicMock()
    mock_order_repo = AsyncMock()
    mock_pharm_repo = AsyncMock()
    mock_pay_service = AsyncMock()

    service = OrderService(mock_order_repo, mock_pharm_repo, mock_pay_service, mock_db)

    item_sample = {
        'medicine_id': 'med_1',
        'name': 'Napa Extra',
        'brand': 'Napa',
        'strength': '500mg',
        'unit_price': 2.5,
        'quantity': 5,
        'total_price': 12.5
    }

    mock_order_repo.get_order_by_id.return_value = {
        'id': 'ord_100',
        'order_number': 'ORD-100',
        'user_id': 'user_1',
        'status': OrderStatus.CONFIRMED.value,
        'items': [item_sample],
        'delivery_address': {'recipient_name': 'Test', 'street_address': 'X', 'district': 'Dhaka', 'division': 'Dhaka', 'upazila_or_thana': 'Dhanmondi', 'recipient_phone': '017'}
    }
    mock_order_repo.update_order_status.side_effect = lambda order_id, new_status, tracking_note: {
        **mock_order_repo.get_order_by_id.return_value,
        'status': new_status.value if hasattr(new_status, 'value') else new_status
    }
    mock_db.medicines.update_one = AsyncMock()
    mock_db.notifications.insert_one = AsyncMock()
    mock_db.audit_logs.insert_one = AsyncMock()

    cancel_res = await service.cancel_order('ord_100', 'user_1', UserRole.USER.value, reason='Ordered by mistake')
    assert cancel_res.status == OrderStatus.CANCELLED
    mock_db.medicines.update_one.assert_called_with(
        {'id': 'med_1'},
        {'': {'stock_count': 5}, '': {'in_stock': True}}
    )

    mock_order_repo.get_order_by_id.return_value = {
        'id': 'ord_200',
        'order_number': 'ORD-200',
        'user_id': 'user_1',
        'status': OrderStatus.SHIPPED.value,
        'items': [item_sample],
        'delivery_address': {'recipient_name': 'Test', 'street_address': 'X', 'district': 'Dhaka', 'division': 'Dhaka', 'upazila_or_thana': 'Dhanmondi', 'recipient_phone': '017'}
    }

    with pytest.raises(BadRequestException) as exc:
        await service.cancel_order('ord_200', 'user_1', UserRole.USER.value)

    assert 'cannot be cancelled because it is already SHIPPED' in str(exc.value)

@pytest.mark.asyncio
async def test_admin_realtime_broadcaster():
    broadcaster = OrderEventBroadcaster()
    queue = await broadcaster.subscribe()

    test_data = {'id': 'ord_999', 'status': 'CONFIRMED'}
    await broadcaster.broadcast('order_created', test_data)

    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event['event'] == 'order_created'
    assert event['data']['id'] == 'ord_999'

    await broadcaster.unsubscribe(queue)
