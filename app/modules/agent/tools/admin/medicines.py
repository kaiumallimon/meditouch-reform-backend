from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.security.confirmation import confirmation_manager
from app.modules.agent.tools.resolver import EntityResolver
from app.common.enums import UserRole

class CreateMedicineTool(BaseTool):
    name = "create_medicine"
    description = "Adds a new medicine to the pharmacy catalog with brand name, generic, pricing, and stock."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "brand": {"type": "string", "description": "Brand name of the medicine (e.g. 'Napa Extra')"},
            "generic_name": {"type": "string", "description": "Active generic chemical name (e.g. 'Paracetamol + Caffeine')"},
            "dosage_form": {"type": "string", "description": "Form: Tablet, Capsule, Syrup, Injection, Suspension, Drop", "default": "Tablet"},
            "strength": {"type": "string", "description": "Strength (e.g. '500mg + 65mg')"},
            "unit_price": {"type": "number", "description": "Price per unit in BDT (e.g. 2.50)"},
            "price_pack": {"type": "number", "description": "Price per box/strip (e.g. 250.00)"},
            "pack_size": {"type": "string", "description": "Packaging size (e.g. '100 tablets/box')", "default": "10x10 Tablets"},
            "manufacturer": {"type": "string", "description": "Pharmaceutical manufacturer (e.g. 'Beximco Pharmaceuticals Ltd.')"},
            "stock_count": {"type": "integer", "description": "Initial inventory stock count", "default": 100},
            "requires_prescription": {"type": "boolean", "description": "Whether an Rx prescription is required", "default": False},
        },
        "required": ["brand", "generic_name", "unit_price"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        brand = arguments["brand"].strip()
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", brand.lower()).strip("-") + f"-{str(uuid.uuid4())[:6]}"
        now = datetime.now(timezone.utc)

        doc = {
            "id": f"med_{uuid.uuid4()}",
            "brand": brand,
            "name": brand,
            "medicine_name": brand,
            "generic_name": arguments["generic_name"].strip(),
            "dosage_form": arguments.get("dosage_form", "Tablet"),
            "strength": arguments.get("strength", "500mg"),
            "unit_price": float(arguments["unit_price"]),
            "price_pack": float(arguments.get("price_pack", arguments["unit_price"] * 10)),
            "pack_size": arguments.get("pack_size", "10x10 Tablets"),
            "manufacturer": arguments.get("manufacturer", "Square Pharmaceuticals"),
            "manufacturer_name": arguments.get("manufacturer", "Square Pharmaceuticals"),
            "stock_count": int(arguments.get("stock_count", 100)),
            "in_stock": int(arguments.get("stock_count", 100)) > 0,
            "requires_prescription": bool(arguments.get("requires_prescription", False)),
            "slug": slug,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        await self.db.medicines.insert_one(doc)
        doc.pop("_id", None)

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result=doc,
            metadata={"action": "CREATE_MEDICINE", "medicine_id": doc["id"], "brand": brand},
        )

class UpdateMedicineStockTool(BaseTool):
    name = "update_medicine_stock"
    description = "Updates the inventory stock count for a medicine."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "medicine": {"type": "string", "description": "Medicine identifier: name, slug, or ID"},
            "new_stock": {"type": "integer", "description": "Absolute new stock count"},
            "quantity_delta": {"type": "integer", "description": "Optional relative delta (+50 or -20)"},
        },
        "required": ["medicine"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.resolver = EntityResolver(db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        query = arguments["medicine"].strip()
        res = await self.resolver.resolve_medicine(query)
        if res["status"] == "NOT_FOUND":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"Medicine not found: {query}")
        elif res["status"] == "AMBIGUOUS":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.SUCCESS, result={"candidates": res["candidates"], "message": f"Multiple medicines matched '{query}'. Please specify exact strength/slug."})

        med = res["match"]
        current_stock = med.get("stock_count", 0)

        if "new_stock" in arguments:
            final_stock = max(0, int(arguments["new_stock"]))
        elif "quantity_delta" in arguments:
            final_stock = max(0, current_stock + int(arguments["quantity_delta"]))
        else:
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Please specify either new_stock or quantity_delta.")

        now = datetime.now(timezone.utc)
        await self.db.medicines.update_one(
            {"id": med["id"]},
            {"$set": {"stock_count": final_stock, "in_stock": final_stock > 0, "updated_at": now}}
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={
                "id": med["id"],
                "brand": med.get("brand"),
                "previous_stock": current_stock,
                "new_stock": final_stock,
                "in_stock": final_stock > 0,
            },
            metadata={"action": "UPDATE_STOCK", "medicine_id": med["id"]},
        )

class DeleteMedicineTool(BaseTool):
    name = "delete_medicine"
    description = "Removes or deactivates a medicine from the catalog. Requires 2-step confirmation."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = True
    parameters = {
        "type": "object",
        "properties": {
            "medicine": {"type": "string", "description": "Medicine identifier: brand, slug, or ID"},
        },
        "required": ["medicine"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.resolver = EntityResolver(db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if not self.is_authorized(caller_role):
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.PERMISSION_DENIED, result=None, error_message="Admin privileges required")

        if confirmation_token:
            payload = confirmation_manager.validate_and_consume(confirmation_token, session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid or expired confirmation token")
            
            med_id = payload["target_id"]
            now = datetime.now(timezone.utc)
            await self.db.medicines.update_one({"id": med_id}, {"$set": {"is_active": False, "is_deleted": True, "updated_at": now}})
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"id": med_id, "status": "DELETED"},
                metadata={"action": "DELETE_MEDICINE", "medicine_id": med_id},
            )

        query = arguments["medicine"].strip()
        res = await self.resolver.resolve_medicine(query)
        if res["status"] == "NOT_FOUND":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"Medicine not found: {query}")
        elif res["status"] == "AMBIGUOUS":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.SUCCESS, result={"candidates": res["candidates"], "message": f"Multiple medicines matched '{query}'. Please specify exact strength."})

        med = res["match"]
        token = confirmation_manager.create_pending_confirmation(
            session_id=session_id,
            action="delete_medicine",
            target_type="MEDICINE",
            target_id=med["id"],
            target_name=med.get("brand"),
            summary=f"Delete medicine {med.get('brand')} (ID: {med['id']})",
            command_data={"medicine_id": med["id"]},
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={"id": med["id"], "brand": med.get("brand"), "generic": med.get("generic_name")},
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"🚨 DESTRUCTIVE OPERATION: Delete medicine '{med.get('brand')}' ({med.get('generic_name')}) from catalog? Confirm?",
        )
