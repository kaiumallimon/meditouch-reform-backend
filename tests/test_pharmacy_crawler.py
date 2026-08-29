import pytest
from app.modules.pharmacy.crawler import resolve_full_image_url

def test_resolve_full_image_url():
    base = "https://api.medeasy.health"
    # Relative path starting with slash
    res1 = resolve_full_image_url(base, "/media/medicines/IMG-20231019-WA0397.jpg")
    assert res1 == "https://api.medeasy.health/media/medicines/IMG-20231019-WA0397.jpg"

    # Relative path without leading slash
    res2 = resolve_full_image_url(base, "media/medicines/medeasy_ceevit_250.jpg")
    assert res2 == "https://api.medeasy.health/media/medicines/medeasy_ceevit_250.jpg"

    # Already absolute url
    res3 = resolve_full_image_url(base, "https://res.cloudinary.com/m2nxsbff/image/upload/v1/test.png")
    assert res3 == "https://res.cloudinary.com/m2nxsbff/image/upload/v1/test.png"

    # None or empty
    assert resolve_full_image_url(base, None) is None
    assert resolve_full_image_url(base, "") is None

@pytest.mark.asyncio
async def test_crawler_settings_and_status(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Get default settings
    get_res = await client.get("/api/v1/pharmacy/crawler/settings", headers=headers)
    assert get_res.status_code == 200
    settings = get_res.json()["data"]
    assert "api_base_url" in settings
    assert "session_id" in settings
    assert settings["category_slug"] == "otc-medicine"

    # 2. Update settings
    update_payload = {
        "session_id": "uWWQE90f364vl5aK7aV00",
        "rate_limit_delay_seconds": 0.1
    }
    put_res = await client.put("/api/v1/pharmacy/crawler/settings", json=update_payload, headers=headers)
    assert put_res.status_code == 200
    assert put_res.json()["data"]["session_id"] == "uWWQE90f364vl5aK7aV00"
    assert put_res.json()["data"]["rate_limit_delay_seconds"] == 0.1

    # 3. Get crawler status
    status_res = await client.get("/api/v1/pharmacy/crawler/status", headers=headers)
    assert status_res.status_code == 200
    status_data = status_res.json()["data"]
    assert "status" in status_data

@pytest.mark.asyncio
async def test_medicine_details_and_idempotency(client, admin_auth, mock_db):
    headers = admin_auth["headers"]

    # 1. Create a medicine directly in database with rich details
    slug = "coralcal-d-tablet"
    med_id = "test-coralcal-uuid"

    await mock_db.medicines.delete_many({"slug": slug})
    await mock_db.medicine_details.delete_many({"slug": slug})

    await mock_db.medicines.insert_one({
        "id": med_id,
        "medeasy_id": 4087,
        "medicine_name": "CoralCal-D",
        "name": "CoralCal-D Tablet",
        "brand": "CoralCal-D",
        "generic_name": "Calcium Carbonate [Coral source] + Vitamin D3",
        "strength": "500 mg + 200 IU",
        "dosage_form": "Tablet",
        "category": "TABLET",
        "category_name": "Tablet",
        "category_slug": "otc-medicine",
        "slug": slug,
        "manufacturer": "Radiant Pharmaceuticals Ltd.",
        "manufacturer_name": "Radiant Pharmaceuticals Ltd.",
        "unit_price": 13.0,
        "pack_size": "10's Strip",
        "unit_prices": [
            {"unit": "10's Strip", "unit_size": 10, "price": 130.0},
            {"unit": "60's pack", "unit_size": 60, "price": 780.0}
        ],
        "discount_type": "Percentage",
        "discount_value": 10.0,
        "is_available": True,
        "rx_required": False,
        "requires_prescription": False,
        "medicine_image": "https://api.medeasy.health/media/medicines/IMG-20231219-WA0088.jpg",
        "in_stock": True,
        "stock_count": 150,
        "is_active": True,
        "source": "MedEasy"
    })

    await mock_db.medicine_details.insert_one({
        "id": "detail-coralcal-uuid",
        "medicine_id": med_id,
        "slug": slug,
        "medicine_name": "CoralCal-D",
        "generic_name": "Calcium Carbonate [Coral source] + Vitamin D3",
        "category_name": "Tablet",
        "category_slug": "otc-medicine",
        "manufacturer_name": "Radiant Pharmaceuticals Ltd.",
        "meta_title": "Calcium Carbonate [Coral source] + Vitamin D3: Uses, Dosage",
        "medicine_details": {
            "Indications": "<p>Indicated for dietary calcium deficiency.</p>",
            "Dosage And Administration": "<p>1 tablet once or twice daily.</p>",
            "Pharmacology": "<p>Calcium carbonate dissociates in stomach acid.</p>",
            "Side Effects": "<p>Constipation, bloating.</p>"
        },
        "related_medicines": []
    })

    # 2. Query basic medicine
    get_med_res = await client.get(f"/api/v1/pharmacy/medicines/{slug}")
    assert get_med_res.status_code == 200
    med_res_data = get_med_res.json()["data"]
    assert med_res_data["medicine_name"] == "CoralCal-D"
    assert med_res_data["slug"] == slug
    assert len(med_res_data["unit_prices"]) == 2

    # 3. Query rich details monograph
    get_detail_res = await client.get(f"/api/v1/pharmacy/medicines/{slug}/details")
    assert get_detail_res.status_code == 200
    detail_res_data = get_detail_res.json()["data"]
    assert detail_res_data["slug"] == slug
    assert "Indications" in detail_res_data["medicine_details"]
    assert "Dosage And Administration" in detail_res_data["medicine_details"]

    # 4. Check pharmacy stats endpoint
    stats_res = await client.get("/api/v1/pharmacy/stats")
    assert stats_res.status_code == 200
    stats_data = stats_res.json()["data"]
    assert stats_data["total_medicines"] >= 1
    assert stats_data["total_categories"] >= 1
    assert stats_data["total_manufacturers"] >= 1

