import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.modules.inventory.service import InventoryService
from app.modules.inventory.schemas import (
    RestockRequest,
    StockAdjustmentRequest,
    UpdateItemThresholdsRequest
)
from app.common.enums import StockMovementType

@pytest.mark.asyncio
async def test_inventory_overview_calculation():
    mock_db = MagicMock()
    
    # Mock aggregate for medicines
    mock_db.medicines.aggregate.return_value.to_list = AsyncMock(return_value=[{
        "total_skus": 150,
        "total_stock_units": 12500,
        "total_valuation_bdt": 450000.5,
        "in_stock_skus": 130,
        "low_stock_skus": 12,
        "out_of_stock_skus": 8
    }])

    # Mock count_documents for batches
    async def mock_batch_counts(query):
        if "expiry_date" in query and "$lte" in query["expiry_date"]:
            if "$gt" in query["expiry_date"]:
                return 5  # expiring soon
            return 2  # expired
        return 20  # active
    mock_db.inventory_batches.count_documents = AsyncMock(side_effect=mock_batch_counts)

    service = InventoryService(mock_db)
    overview = await service.get_overview()

    assert overview.total_skus == 150
    assert overview.total_stock_units == 12500
    assert overview.total_valuation_bdt == 450000.5
    assert overview.in_stock_skus == 130
    assert overview.low_stock_skus == 12
    assert overview.out_of_stock_skus == 8
    assert overview.active_batches == 20
    assert overview.expiring_soon_batches == 5
    assert overview.expired_batches == 2

@pytest.mark.asyncio
async def test_inventory_restock_purchase_inward():
    mock_db = MagicMock()
    
    medicine_doc = {
        "id": "med_101",
        "brand": "Napa Extra",
        "name": "Napa Extra",
        "stock_count": 25,
        "unit_price": 3.0
    }
    mock_db.medicines.find_one = AsyncMock(return_value=medicine_doc)
    
    # Mock update stock
    async def mock_update_medicine(filter_query, update_query, return_document=None):
        inc = update_query.get("$inc", {}).get("stock_count", 0)
        return {**medicine_doc, "stock_count": medicine_doc["stock_count"] + inc}
    mock_db.medicines.find_one_and_update = AsyncMock(side_effect=mock_update_medicine)

    inserted_batches = []
    async def mock_insert_batch(doc):
        inserted_batches.append(doc)
    mock_db.inventory_batches.insert_one = AsyncMock(side_effect=mock_insert_batch)

    inserted_txs = []
    async def mock_insert_tx(doc):
        inserted_txs.append(doc)
    mock_db.inventory_transactions.insert_one = AsyncMock(side_effect=mock_insert_tx)
    mock_db.audit_logs.insert_one = AsyncMock()

    service = InventoryService(mock_db)

    req = RestockRequest(
        medicine_id="med_101",
        batch_number="BX-2026-99",
        expiry_date=datetime.now(timezone.utc) + timedelta(days=365),
        supplier_name="Beximco Pharma",
        supplier_invoice_no="INV-8821",
        quantity_received=100,
        purchase_price_bdt=2.4,
        mrp_bdt=3.0,
        notes="Q3 Standard Restock"
    )

    res = await service.restock(req, admin_id="admin_1", admin_name="Super Admin")

    assert res["success"] is True
    assert res["previous_stock"] == 25
    assert res["new_stock"] == 125
    assert len(inserted_batches) == 1
    assert inserted_batches[0]["batch_number"] == "BX-2026-99"
    assert inserted_batches[0]["quantity_available"] == 100
    assert len(inserted_txs) == 1
    assert inserted_txs[0]["transaction_type"] == StockMovementType.PURCHASE_INWARD.value
    assert inserted_txs[0]["quantity_delta"] == 100
    assert inserted_txs[0]["previous_stock"] == 25
    assert inserted_txs[0]["new_stock"] == 125

@pytest.mark.asyncio
async def test_inventory_adjustment_write_off():
    mock_db = MagicMock()
    
    medicine_doc = {
        "id": "med_102",
        "brand": "Ace Plus",
        "name": "Ace Plus",
        "stock_count": 50,
        "unit_price": 2.5
    }
    mock_db.medicines.find_one = AsyncMock(return_value=medicine_doc)
    mock_db.medicines.find_one_and_update = AsyncMock(return_value={**medicine_doc, "stock_count": 45})
    
    batch_doc = {
        "id": "batch_abc",
        "batch_number": "LOT-102",
        "quantity_available": 30
    }
    mock_db.inventory_batches.find_one = AsyncMock(return_value=batch_doc)
    mock_db.inventory_batches.find_one_and_update = AsyncMock()

    inserted_txs = []
    mock_db.inventory_transactions.insert_one = AsyncMock(side_effect=lambda doc: inserted_txs.append(doc))
    mock_db.audit_logs.insert_one = AsyncMock()

    service = InventoryService(mock_db)

    req = StockAdjustmentRequest(
        medicine_id="med_102",
        batch_id="batch_abc",
        movement_type=StockMovementType.DAMAGE_WRITE_OFF,
        quantity_delta=-5,
        reason="Crushed during shelf restocking",
        notes="Write-off approved by pharmacy head"
    )

    res = await service.adjust_stock(req, admin_id="admin_1", admin_name="Admin")

    assert res["success"] is True
    assert res["previous_stock"] == 50
    assert res["new_stock"] == 45
    assert res["quantity_delta"] == -5
    assert len(inserted_txs) == 1
    assert inserted_txs[0]["transaction_type"] == StockMovementType.DAMAGE_WRITE_OFF.value
    assert inserted_txs[0]["quantity_delta"] == -5

@pytest.mark.asyncio
async def test_inventory_export_csv():
    mock_db = MagicMock()
    
    medicines = [
        {
            "id": "med_1",
            "brand": "Napa",
            "generic_name": "Paracetamol",
            "dosage_form": "Tablet",
            "strength": "500mg",
            "manufacturer": "Beximco",
            "unit_price": 1.2,
            "stock_count": 200,
            "min_stock_alert": 20,
            "shelf_location": "Rack A1"
        },
        {
            "id": "med_2",
            "brand": "Seclo",
            "generic_name": "Omeprazole",
            "dosage_form": "Capsule",
            "strength": "20mg",
            "manufacturer": "Square",
            "unit_price": 5.0,
            "stock_count": 0,
            "min_stock_alert": 15,
            "shelf_location": "Rack B3"
        }
    ]
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=medicines)
    mock_db.medicines.find.return_value = cursor

    service = InventoryService(mock_db)
    csv_str = await service.export_inventory_csv()

    assert "Item ID,Brand Name,Generic Name" in csv_str
    assert "Napa,Paracetamol,Tablet,500mg,Beximco,1.2,200,20,240.0,Rack A1,IN_STOCK" in csv_str
    assert "Seclo,Omeprazole,Capsule,20mg,Square,5.0,0,15,0.0,Rack B3,OUT_OF_STOCK" in csv_str
