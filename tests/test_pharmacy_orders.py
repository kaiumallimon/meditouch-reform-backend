import pytest

@pytest.mark.asyncio
async def test_pharmacy_catalog_search_and_cart(client, patient_auth):
    headers = patient_auth["headers"]

    # 1. Search medicines from ingested catalog
    search_res = await client.get("/api/v1/pharmacy/medicines?search=Napa")
    assert search_res.status_code == 200
    medicines = search_res.json()["data"]["items"]
    assert len(medicines) >= 1
    med1 = medicines[0]

    # 2. Add to cart
    add_res = await client.post(
        "/api/v1/orders/cart/items",
        json={"medicine_id": med1["id"], "quantity": 3},
        headers=headers
    )
    assert add_res.status_code == 200
    cart_data = add_res.json()["data"]
    assert cart_data["items_count"] == 1
    assert cart_data["items"][0]["quantity"] == 3
    assert cart_data["subtotal"] > 0

    # 3. View Cart
    get_cart_res = await client.get("/api/v1/orders/cart", headers=headers)
    assert get_cart_res.status_code == 200
    assert get_cart_res.json()["data"]["delivery_fee"] == 60.0

@pytest.mark.asyncio
async def test_pharmacy_checkout_and_inventory_decrement(client, admin_auth, patient_auth):
    patient_headers = patient_auth["headers"]
    admin_headers = admin_auth["headers"]

    # 1. Find a medicine
    search_res = await client.get("/api/v1/pharmacy/medicines?search=Seclo")
    assert search_res.status_code == 200
    med = search_res.json()["data"]["items"][0]
    med_id = med["id"]
    initial_stock = med["stock_count"]

    # 2. Add to cart
    await client.post("/api/v1/orders/cart/items", json={"medicine_id": med_id, "quantity": 5}, headers=patient_headers)

    # 3. Checkout
    checkout_payload = {
        "delivery_address": {
            "recipient_name": "Kamal Hossain",
            "recipient_phone": "01800000003",
            "division": "Dhaka",
            "district": "Dhaka",
            "upazila_or_thana": "Mirpur",
            "street_address": "House 12, Road 4, Section 10",
            "is_default": True
        },
        "customer_notes": "Please call before arrival"
    }
    co_res = await client.post("/api/v1/orders/checkout", json=checkout_payload, headers=patient_headers)
    assert co_res.status_code == 201
    order_data = co_res.json()["data"]
    assert order_data["status"] == "PENDING_PAYMENT"
    bkash_payment_id = order_data["payment_url"].split("paymentID=")[-1]
    order_id = order_data["id"]

    # 4. Confirm Payment Callback
    pay_res = await client.post(f"/api/v1/payments/bkash/callback?paymentID={bkash_payment_id}&status=success")
    assert pay_res.status_code == 200

    # 5. Verify Order is CONFIRMED
    get_order_res = await client.get(f"/api/v1/orders/{order_id}", headers=patient_headers)
    assert get_order_res.status_code == 200
    assert get_order_res.json()["data"]["status"] == "CONFIRMED"

    # 6. Verify stock count decremented atomically
    med_after_res = await client.get(f"/api/v1/pharmacy/medicines/{med_id}")
    assert med_after_res.json()["data"]["stock_count"] == initial_stock - 5

    # 7. Admin updates order tracking status
    status_update = {
        "status": "SHIPPED",
        "tracking_note": "Dispatched via RedX Courier. Tracking code: RDX-88392"
    }
    stat_res = await client.put(f"/api/v1/orders/{order_id}/status", json=status_update, headers=admin_headers)
    assert stat_res.status_code == 200
    assert stat_res.json()["data"]["status"] == "SHIPPED"
    assert len(stat_res.json()["data"]["tracking_history"]) >= 2
