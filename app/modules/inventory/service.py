from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import io
import csv

from app.modules.inventory.repository import InventoryRepository
from app.modules.inventory.schemas import (
    InventoryOverviewResponse,
    RestockRequest,
    StockAdjustmentRequest,
    UpdateItemThresholdsRequest
)
from app.common.enums import StockMovementType, AuditAction, BatchStatus
from app.core.exceptions import NotFoundException, BadRequestException
from app.modules.admin.service import log_audit_event

class InventoryService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = InventoryRepository(db)

    async def get_overview(self) -> InventoryOverviewResponse:
        metrics = await self.repo.get_overview_metrics()
        return InventoryOverviewResponse(**metrics)

    async def get_items(
        self,
        search: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        sort_by: Optional[str] = "stock_desc",
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        return await self.repo.get_inventory_items(
            search=search,
            status=status,
            category=category,
            sort_by=sort_by,
            page=page,
            limit=limit
        )

    async def get_item_details(self, medicine_id: str) -> Dict[str, Any]:
        med = await self.repo.get_medicine_by_id_or_slug(medicine_id)
        if not med:
            raise NotFoundException("Medicine not found in inventory")

        real_id = med.get("id") or str(med.get("_id", ""))
        batches = await self.repo.get_batches_for_medicine(real_id)
        recent_txs = await self.repo.get_transactions(medicine_id=real_id, limit=10)

        stock_count = int(med.get("stock_count", 0))
        min_stock = int(med.get("min_stock_alert", 10))
        status = "OUT_OF_STOCK" if stock_count <= 0 else ("LOW_STOCK" if stock_count <= min_stock else "IN_STOCK")

        med_info = {
            "id": real_id,
            "name": med.get("name") or med.get("medicine_name") or med.get("brand"),
            "brand": med.get("brand"),
            "generic_name": med.get("generic_name"),
            "strength": med.get("strength"),
            "dosage_form": med.get("dosage_form"),
            "category": med.get("category"),
            "manufacturer": med.get("manufacturer"),
            "unit_price": float(med.get("unit_price", 0.0)),
            "stock_count": stock_count,
            "min_stock_alert": min_stock,
            "reorder_quantity": int(med.get("reorder_quantity", 50)),
            "shelf_location": med.get("shelf_location") or "Main Storage",
            "in_stock": stock_count > 0,
            "status": status,
            "medicine_image": med.get("medicine_image"),
            "image_url": med.get("medicine_image")
        }

        tx_items = recent_txs.get("items", [])

        return {
            "medicine": med_info,
            "item": med_info,
            "batches": batches,
            "transactions": tx_items,
            "recent_transactions": tx_items
        }

    async def restock(
        self,
        req: RestockRequest,
        admin_id: Optional[str] = None,
        admin_name: Optional[str] = None
    ) -> Dict[str, Any]:
        med = await self.repo.get_medicine_by_id_or_slug(req.medicine_id)
        if not med:
            raise NotFoundException(f"Medicine '{req.medicine_id}' not found")

        real_id = med.get("id") or str(med.get("_id", ""))
        med_name = med.get("name") or med.get("medicine_name") or med.get("brand") or "Medicine"
        previous_stock = int(med.get("stock_count", 0))

        # 1. Create Batch record
        batch_data = {
            "medicine_id": real_id,
            "medicine_name": med_name,
            "batch_number": req.batch_number.strip().upper(),
            "expiry_date": req.expiry_date,
            "manufacturing_date": req.manufacturing_date,
            "supplier_name": req.supplier_name.strip(),
            "supplier_invoice_no": (req.supplier_invoice_no or "").strip(),
            "quantity_received": req.quantity_received,
            "quantity_available": req.quantity_received,
            "quantity_sold": 0,
            "quantity_discarded": 0,
            "purchase_price_bdt": req.purchase_price_bdt,
            "mrp_bdt": req.mrp_bdt if req.mrp_bdt is not None else float(med.get("unit_price", 0.0)),
            "status": "ACTIVE"
        }
        created_batch = await self.repo.create_batch(batch_data)

        # 2. Update Medicine aggregate stock
        new_stock = previous_stock + req.quantity_received
        await self.repo.update_medicine_stock_and_flags(
            medicine_id=real_id,
            delta=req.quantity_received
        )

        # 3. Create Stock Movement Ledger entry
        tx_data = {
            "medicine_id": real_id,
            "medicine_name": med_name,
            "batch_id": created_batch["id"],
            "batch_number": req.batch_number.strip().upper(),
            "transaction_type": StockMovementType.PURCHASE_INWARD.value,
            "quantity_delta": req.quantity_received,
            "previous_stock": previous_stock,
            "new_stock": new_stock,
            "reference_id": req.supplier_invoice_no or created_batch["id"],
            "actor_id": admin_id,
            "actor_name": admin_name or "Administrator",
            "reason": f"Restocked {req.quantity_received} units from {req.supplier_name}",
            "created_at": datetime.now(timezone.utc)
        }
        await self.repo.create_transaction(tx_data)

        # 4. Audit logging
        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.INVENTORY_RESTOCKED,
            target_type="INVENTORY",
            target_id=real_id,
            details={
                "batch_number": req.batch_number,
                "quantity": req.quantity_received,
                "supplier": req.supplier_name,
                "previous_stock": previous_stock,
                "new_stock": new_stock
            }
        )

        return {
            "success": True,
            "medicine_id": real_id,
            "batch": created_batch,
            "previous_stock": previous_stock,
            "new_stock": new_stock
        }

    async def adjust_stock(
        self,
        req: StockAdjustmentRequest,
        admin_id: Optional[str] = None,
        admin_name: Optional[str] = None
    ) -> Dict[str, Any]:
        med = await self.repo.get_medicine_by_id_or_slug(req.medicine_id)
        if not med:
            raise NotFoundException(f"Medicine '{req.medicine_id}' not found")

        real_id = med.get("id") or str(med.get("_id", ""))
        med_name = med.get("name") or med.get("medicine_name") or med.get("brand") or "Medicine"
        previous_stock = int(med.get("stock_count", 0))

        # Check that we cannot adjust below 0
        new_stock = max(0, previous_stock + req.quantity_delta)
        effective_delta = new_stock - previous_stock

        batch_number = None
        if req.batch_id:
            batch = await self.repo.find_batch_by_id(req.batch_id)
            if batch:
                batch_number = batch.get("batch_number")
                # Adjust batch available
                cur_batch_qty = batch.get("quantity_available", 0)
                new_batch_qty = max(0, cur_batch_qty + req.quantity_delta)
                await self.repo.update_batch_quantity(req.batch_id, new_batch_qty - cur_batch_qty)

        # Update Medicine stock
        await self.repo.update_medicine_stock_and_flags(
            medicine_id=real_id,
            delta=effective_delta,
            set_stock=new_stock
        )

        # Write to Ledger
        tx_data = {
            "medicine_id": real_id,
            "medicine_name": med_name,
            "batch_id": req.batch_id,
            "batch_number": batch_number,
            "transaction_type": req.movement_type.value,
            "quantity_delta": effective_delta,
            "previous_stock": previous_stock,
            "new_stock": new_stock,
            "reference_id": f"ADJ-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "actor_id": admin_id,
            "actor_name": admin_name or "Administrator",
            "reason": req.reason + (f" ({req.notes})" if req.notes else ""),
            "created_at": datetime.now(timezone.utc)
        }
        await self.repo.create_transaction(tx_data)

        # Log audit
        await log_audit_event(
            self.db,
            user_id=admin_id,
            action=AuditAction.INVENTORY_ADJUSTED,
            target_type="INVENTORY",
            target_id=real_id,
            details={
                "movement_type": req.movement_type.value,
                "delta": effective_delta,
                "reason": req.reason,
                "previous_stock": previous_stock,
                "new_stock": new_stock
            }
        )

        return {
            "success": True,
            "medicine_id": real_id,
            "previous_stock": previous_stock,
            "new_stock": new_stock,
            "quantity_delta": effective_delta
        }

    async def update_thresholds(
        self,
        medicine_id: str,
        req: UpdateItemThresholdsRequest
    ) -> Dict[str, Any]:
        updated = await self.repo.update_thresholds(
            medicine_id=medicine_id,
            min_stock_alert=req.min_stock_alert,
            reorder_quantity=req.reorder_quantity,
            shelf_location=req.shelf_location
        )
        if not updated:
            raise NotFoundException("Medicine not found")
        return {"success": True, "message": "Inventory thresholds updated successfully"}

    async def get_batches(
        self,
        search: Optional[str] = None,
        filter_status: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        return await self.repo.get_all_batches(
            search=search,
            filter_status=filter_status,
            page=page,
            limit=limit
        )

    async def get_transactions(
        self,
        medicine_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        return await self.repo.get_transactions(
            medicine_id=medicine_id,
            transaction_type=transaction_type,
            search=search,
            page=page,
            limit=limit
        )

    async def export_inventory_csv(self) -> str:
        cursor = self.db.medicines.find({}).sort("stock_count", -1)
        medicines = await cursor.to_list(5000)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Item ID",
            "Brand Name",
            "Generic Name",
            "Dosage Form",
            "Strength",
            "Manufacturer",
            "Unit Price (BDT)",
            "Stock On Hand",
            "Min Alert Threshold",
            "Inventory Valuation (BDT)",
            "Shelf Location",
            "Status"
        ])

        for m in medicines:
            stock = int(m.get("stock_count", 0))
            price = float(m.get("unit_price", 0.0))
            min_alert = int(m.get("min_stock_alert", 10))
            valuation = round(stock * price, 2)
            status = "OUT_OF_STOCK" if stock <= 0 else ("LOW_STOCK" if stock <= min_alert else "IN_STOCK")

            writer.writerow([
                m.get("id") or str(m.get("_id", "")),
                m.get("brand") or m.get("name") or "Medicine",
                m.get("generic_name") or "",
                m.get("dosage_form") or "Tablet",
                m.get("strength") or "",
                m.get("manufacturer") or "Pharma",
                price,
                stock,
                min_alert,
                valuation,
                m.get("shelf_location") or "Main Storage",
                status
            ])

        return output.getvalue()
