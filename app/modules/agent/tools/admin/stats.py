from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.admin.repository import AdminRepository
from app.common.enums import UserRole

class GetPlatformSummaryStatsTool(BaseTool):
    name = "get_platform_summary_stats"
    description = "Queries real-time platform metrics: total users, active doctors, pending verifications, consultations, total orders, and total revenue."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.admin_repo = AdminRepository(db)

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

        stats = await self.admin_repo.get_dashboard_stats()
        med_count = await self.db.medicines.count_documents({"is_active": True})
        low_stock = await self.db.medicines.count_documents({"is_active": True, "stock_count": {"$lt": 20}})

        stats["total_catalog_medicines"] = med_count
        stats["low_stock_medicines_count"] = low_stock

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result=stats,
            metadata={"action": "GET_PLATFORM_STATS"},
        )

class QueryAuditLogsTool(BaseTool):
    name = "query_audit_logs"
    description = "Queries the immutable system audit logs for administrative security monitoring."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "search": {"type": "string", "description": "Search keyword in action, target, or user"},
            "action": {"type": "string", "description": "Filter by action (e.g., 'CREATE_USER', 'DELETE_USER', 'VERIFY_DOCTOR')"},
            "limit": {"type": "integer", "description": "Max logs to retrieve (default: 10)", "default": 10},
        },
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.admin_repo = AdminRepository(db)

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

        limit = min(int(arguments.get("limit", 10)), 30)
        logs, total = await self.admin_repo.get_audit_logs(
            limit=limit,
            search=arguments.get("search"),
            action=arguments.get("action"),
        )

        clean_logs = [
            {
                "action": l.get("action"),
                "target_type": l.get("target_type"),
                "target_id": l.get("target_id"),
                "user_id": l.get("user_id"),
                "ip_address": l.get("ip_address"),
                "created_at": str(l.get("created_at")),
            }
            for l in logs
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={"logs": clean_logs, "total": total},
            metadata={"action": "QUERY_AUDIT_LOGS", "count": len(clean_logs)},
        )

class GetAdminOrdersTool(BaseTool):
    name = "get_all_orders_admin"
    description = "Lists recent pharmacy orders across all users with status, items, amounts, and shipping."
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter: PENDING, PROCESSING, DELIVERED, CANCELLED"},
            "limit": {"type": "integer", "description": "Max orders (default: 10)", "default": 10},
        },
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

        limit = min(int(arguments.get("limit", 10)), 50)
        query: Dict[str, Any] = {}
        if arguments.get("status"):
            query["status"] = arguments["status"].upper()

        cursor = self.db.orders.find(query).sort("created_at", -1).limit(limit)
        orders = await cursor.to_list(length=limit)

        clean = [
            {
                "order_id": o.get("id"),
                "user_id": o.get("user_id"),
                "total_amount": o.get("total_amount", 0.0),
                "status": o.get("status", "PENDING"),
                "items_count": len(o.get("items", [])),
                "created_at": str(o.get("created_at")),
            }
            for o in orders
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={"orders": clean, "total": len(clean)},
            metadata={"action": "GET_ADMIN_ORDERS"},
        )
