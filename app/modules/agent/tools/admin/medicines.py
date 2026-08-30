from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import ValidationError
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.modules.agent.commands.medicine_commands import CreateMedicineCommand, UpdateMedicineCommand
from app.modules.agent.security.pending_actions import AgentPendingActionRepository
from app.modules.agent.tools.resolver import EntityResolver
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.pharmacy.service import PharmacyService
from app.modules.pharmacy.schemas import CreateMedicineRequest, UpdateMedicineRequest
from app.common.enums import UserRole

class CreateMedicineTool(BaseTool):
    name = "create_medicine"
    description = "Adds a new medicine to the pharmacy catalog with brand name, generic, pricing, and stock. Requires admin confirmation."
    capability = ToolCapability.CREATE_MEDICINE
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = True
    is_destructive = False
    requires_confirmation = True
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
        repo = PharmacyRepository(db)
        self.service = PharmacyService(repo, db)
        self.pending_repo = AgentPendingActionRepository(db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        # 1. Pydantic Command Validation
        try:
            cmd = CreateMedicineCommand(
                brand=arguments.get("brand", ""),
                generic_name=arguments.get("generic_name", ""),
                strength=arguments.get("strength", "500mg"),
                dosage_form=arguments.get("dosage_form", "Tablet"),
                unit_price=float(arguments.get("unit_price", 0.0)),
                manufacturer=arguments.get("manufacturer", "Square Pharmaceuticals"),
                stock_count=int(arguments.get("stock_count", 100)),
                requires_prescription=bool(arguments.get("requires_prescription", False)),
            )
        except ValidationError as ve:
            errors = [f"{e['loc'][0]}: {e['msg']}" for e in ve.errors()]
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"Validation failed: {'; '.join(errors)}")
        except Exception as e:
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        # 2. Execution with Verified Pending Action
        if confirmation_token:
            payload = await self.pending_repo.validate_and_consume(confirmation_token, actor_id=caller_id, session_id=session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid, expired, or already executed confirmation token.")

            cdata = payload.get("command_data", arguments)
            req = CreateMedicineRequest(
                brand=cdata["brand"],
                generic_name=cdata["generic_name"],
                dosage_form=cdata.get("dosage_form", "Tablet"),
                strength=cdata.get("strength", "500mg"),
                unit_price=float(cdata["unit_price"]),
                price_pack=float(cdata.get("price_pack", float(cdata["unit_price"]) * 10)),
                pack_size=cdata.get("pack_size", "10x10 Tablets"),
                manufacturer=cdata.get("manufacturer", "Square Pharmaceuticals"),
                stock_count=int(cdata.get("stock_count", 100)),
                requires_prescription=bool(cdata.get("requires_prescription", False)),
            )
            try:
                med = await self.service.create_medicine(req, admin_id=caller_id)
                await self.pending_repo.mark_completed(confirmation_token, {"created_medicine_id": med.id})
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result=med.model_dump(),
                    metadata={"action": "CREATE_MEDICINE", "medicine_id": med.id, "brand": med.brand},
                )
            except Exception as e:
                await self.pending_repo.mark_failed(confirmation_token, str(e))
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        # 3. Create Pending Action for Confirmation
        token = await self.pending_repo.create_pending_action(
            actor_id=caller_id,
            actor_role=caller_role,
            session_id=session_id,
            action="create_medicine",
            target_type="MEDICINE",
            target_id="new_medicine",
            target_name=cmd.brand,
            summary=f"Add medicine {cmd.brand} ({cmd.generic_name}, ৳{cmd.unit_price}/unit, Stock: {cmd.stock_count})",
            command_data=arguments,
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={
                "action": "create_medicine",
                "brand": cmd.brand,
                "generic_name": cmd.generic_name,
                "dosage_form": cmd.dosage_form,
                "strength": cmd.strength,
                "unit_price": cmd.unit_price,
                "stock_count": cmd.stock_count,
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"Add new medicine '{cmd.brand}' ({cmd.generic_name}, Unit Price: ৳{cmd.unit_price}, Initial Stock: {cmd.stock_count}) to the pharmacy catalog? Confirm?",
        )

class UpdateMedicineStockTool(BaseTool):
    name = "update_medicine_stock"
    description = "Updates the inventory stock count for a medicine. Requires admin confirmation."
    capability = ToolCapability.UPDATE_MEDICINE
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = True
    is_destructive = False
    requires_confirmation = True
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
        repo = PharmacyRepository(db)
        self.service = PharmacyService(repo, db)
        self.pending_repo = AgentPendingActionRepository(db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        query = arguments.get("medicine", "").strip()
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

        if confirmation_token:
            payload = await self.pending_repo.validate_and_consume(confirmation_token, actor_id=caller_id, session_id=session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid, expired, or already executed confirmation token.")

            cdata = payload.get("command_data", {})
            stock_to_apply = cdata.get("final_stock", final_stock)

            try:
                req = UpdateMedicineRequest(stock_count=stock_to_apply)
                updated = await self.service.update_medicine(med["id"], req, admin_id=caller_id)
                await self.pending_repo.mark_completed(confirmation_token, {"medicine_id": med["id"], "new_stock": stock_to_apply})

                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result={
                        "id": updated.id,
                        "brand": updated.brand or updated.name,
                        "previous_stock": current_stock,
                        "new_stock": updated.stock_count,
                        "in_stock": updated.in_stock,
                    },
                    metadata={"action": "UPDATE_STOCK", "medicine_id": med["id"]},
                )
            except Exception as e:
                await self.pending_repo.mark_failed(confirmation_token, str(e))
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        token = await self.pending_repo.create_pending_action(
            actor_id=caller_id,
            actor_role=caller_role,
            session_id=session_id,
            action="update_medicine_stock",
            target_type="MEDICINE",
            target_id=med["id"],
            target_name=med.get("brand"),
            summary=f"Update stock for {med.get('brand')} from {current_stock} to {final_stock}",
            command_data={"medicine_id": med["id"], "final_stock": final_stock},
        )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            result={
                "action": "update_medicine_stock",
                "medicine_id": med["id"],
                "brand": med.get("brand"),
                "current_stock": current_stock,
                "proposed_stock": final_stock,
            },
            requires_confirmation=True,
            confirmation_token=token,
            confirmation_prompt=f"Update inventory stock for '{med.get('brand')}' from {current_stock} units to {final_stock} units? Confirm?",
        )

class DeleteMedicineTool(BaseTool):
    name = "delete_medicine"
    description = "Removes or deactivates a medicine from the catalog. Requires 2-step confirmation."
    capability = ToolCapability.DELETE_MEDICINE
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = True
    is_destructive = True
    requires_confirmation = True
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
        repo = PharmacyRepository(db)
        self.service = PharmacyService(repo, db)
        self.pending_repo = AgentPendingActionRepository(db)

    async def execute(
        self,
        arguments: Dict[str, Any],
        caller_id: str,
        caller_role: str,
        session_id: str,
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        if confirmation_token:
            payload = await self.pending_repo.validate_and_consume(confirmation_token, actor_id=caller_id, session_id=session_id)
            if not payload:
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message="Invalid, expired, or already executed confirmation token.")
            
            med_id = payload["target_id"]
            try:
                deleted = await self.service.delete_medicine(med_id, admin_id=caller_id)
                await self.pending_repo.mark_completed(confirmation_token, {"medicine_id": med_id, "deleted": deleted})
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result={"id": med_id, "status": "DELETED"},
                    metadata={"action": "DELETE_MEDICINE", "medicine_id": med_id},
                )
            except Exception as e:
                await self.pending_repo.mark_failed(confirmation_token, str(e))
                return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=str(e))

        query = arguments.get("medicine", "").strip()
        res = await self.resolver.resolve_medicine(query)
        if res["status"] == "NOT_FOUND":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.ERROR, result=None, error_message=f"Medicine not found: {query}")
        elif res["status"] == "AMBIGUOUS":
            return ToolResult(tool_call_id="", name=self.name, status=ToolExecutionStatus.SUCCESS, result={"candidates": res["candidates"], "message": f"Multiple medicines matched '{query}'. Please specify exact strength."})

        med = res["match"]
        token = await self.pending_repo.create_pending_action(
            actor_id=caller_id,
            actor_role=caller_role,
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
