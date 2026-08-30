from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.modules.pharmacy.repository import PharmacyRepository
from app.modules.pharmacy.service import PharmacyService
from app.modules.pharmacy.schemas import MedicineFilterParams
from app.common.pagination import PaginationParams
from app.common.enums import UserRole

class SearchMedicinesTool(BaseTool):
    name = "search_medicines"
    description = "Searches for medicines in the pharmacy catalog by name, brand, or generic."
    capability = ToolCapability.READ_CATALOG
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.NURSE.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search term (e.g., 'Napa', 'Paracetamol', 'Omeprazole')"},
            "requires_prescription": {"type": "boolean", "description": "Filter by OTC (false) or Rx required (true)"},
            "in_stock_only": {"type": "boolean", "description": "Filter only available in-stock items", "default": False},
            "limit": {"type": "integer", "description": "Number of results to return (max 10)", "default": 5},
        },
        "required": ["query"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        repo = PharmacyRepository(db)
        self.service = PharmacyService(repo, db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        query = arguments.get("query", "").strip()
        if not query:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={"count": 0, "medicines": [], "message": "Please specify a brand or generic medicine name to search."},
            )

        rx = arguments.get("requires_prescription")
        in_stock = arguments.get("in_stock_only", False)
        limit = min(int(arguments.get("limit", 5)), 10)

        filters = MedicineFilterParams(search=query, requires_prescription=rx, in_stock_only=in_stock)
        pagination = PaginationParams(page=1, limit=limit)
        res = await self.service.search_catalog(filters, pagination)

        # Filter out cosmetic/skincare products from general medicine search
        items_summary = [
            {
                "id": m.id,
                "slug": m.slug,
                "brand": m.brand or m.name or m.medicine_name,
                "generic_name": m.generic_name,
                "strength": m.strength,
                "dosage_form": m.dosage_form or "Tablet",
                "unit_price": m.unit_price,
                "pack_size": m.pack_size,
                "in_stock": m.in_stock,
                "stock_count": m.stock_count,
                "requires_prescription": bool(m.requires_prescription or m.rx_required),
                "image": m.medicine_image,
                "manufacturer": m.manufacturer or m.manufacturer_name,
            }
            for m in res.items
            if (m.category or "").upper() not in ["SKIN_CARE", "COSMETICS", "BEAUTY", "SKIN CARE"]
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={"count": len(items_summary), "medicines": items_summary, "query": query},
            metadata={"count": len(items_summary)},
        )

class GetMedicineDetailsTool(BaseTool):
    name = "get_medicine_details"
    description = "Retrieves complete factual clinical monograph details for a medicine by slug or ID."
    capability = ToolCapability.MEDICAL_INFORMATION
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.NURSE.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "slug_or_id": {"type": "string", "description": "Medicine slug (e.g. 'napa-extra') or medicine ID"},
        },
        "required": ["slug_or_id"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        repo = PharmacyRepository(db)
        self.service = PharmacyService(repo, db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        slug_or_id = arguments.get("slug_or_id", "").strip()
        try:
            detail = await self.service.get_medicine_detail(slug_or_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result=detail.model_dump(),
            )
        except Exception:
            # Fallback to basic medicine record
            try:
                med = await self.service.get_medicine_by_id_or_slug(slug_or_id)
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.SUCCESS,
                    result=med.model_dump(),
                )
            except Exception:
                return ToolResult(
                    tool_call_id="",
                    name=self.name,
                    status=ToolExecutionStatus.ERROR,
                    result=None,
                    error_message=f"Medicine not found for identifier: {slug_or_id}",
                )

class CheckMedicineStockTool(BaseTool):
    name = "check_medicine_stock"
    description = "Checks current inventory stock count and pricing tiers for a medicine."
    capability = ToolCapability.READ_CATALOG
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.NURSE.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "slug_or_id": {"type": "string", "description": "Medicine slug or ID"},
        },
        "required": ["slug_or_id"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        repo = PharmacyRepository(db)
        self.service = PharmacyService(repo, db)

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        slug_or_id = arguments.get("slug_or_id", "").strip()
        try:
            med = await self.service.get_medicine_by_id_or_slug(slug_or_id)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={
                    "id": med.id,
                    "brand": med.brand or med.name,
                    "unit_price": med.unit_price,
                    "pack_size": med.pack_size,
                    "in_stock": med.in_stock,
                    "stock_count": med.stock_count,
                    "unit_prices": [p.model_dump() for p in med.unit_prices],
                },
            )
        except Exception as e:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message=str(e),
            )
