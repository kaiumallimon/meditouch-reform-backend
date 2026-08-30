from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.common.enums import UserRole

class GetMyProfileTool(BaseTool):
    name = "get_my_profile"
    description = "Retrieves the authenticated caller's user profile (name, email, phone, role, address)."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.NURSE.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {},
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
        user = await self.db.users.find_one({"id": caller_id, "is_deleted": {"$ne": True}})
        if not user:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message="User profile not found.",
            )

        sanitized = {
            "id": user.get("id"),
            "name": user.get("name"),
            "phone": user.get("phone"),
            "email": user.get("email"),
            "role": user.get("role"),
            "gender": user.get("gender"),
            "address": user.get("address"),
            "created_at": str(user.get("created_at")),
        }
        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result=sanitized,
            metadata={"action": "GET_MY_PROFILE", "user_id": caller_id},
        )

class GetMyOrdersTool(BaseTool):
    name = "get_my_orders"
    description = "Retrieves recent pharmacy medicine orders placed by the authenticated user."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.NURSE.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Maximum number of orders to return (default: 5)", "default": 5},
            "status": {"type": "string", "description": "Optional filter by order status (e.g., PENDING, PROCESSING, DELIVERED, CANCELLED)"},
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
        limit = min(int(arguments.get("limit", 5)), 20)
        status = arguments.get("status")

        query: Dict[str, Any] = {"user_id": caller_id}
        if status:
            query["status"] = status.upper()

        cursor = self.db.orders.find(query).sort("created_at", -1).limit(limit)
        orders = await cursor.to_list(length=limit)

        clean_orders = [
            {
                "order_id": o.get("id"),
                "total_amount": o.get("total_amount", 0.0),
                "status": o.get("status", "PENDING"),
                "items_count": len(o.get("items", [])),
                "created_at": str(o.get("created_at")),
                "delivery_address": o.get("shipping_address") or o.get("address"),
            }
            for o in orders
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={"orders": clean_orders, "total": len(clean_orders)},
            metadata={"action": "GET_MY_ORDERS", "user_id": caller_id},
        )

class GetMyAppointmentsTool(BaseTool):
    name = "get_my_appointments"
    description = "Retrieves upcoming and past telemedicine doctor appointments for the authenticated user."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.NURSE.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Maximum number of appointments to return (default: 5)", "default": 5},
            "status": {"type": "string", "description": "Optional status filter: SCHEDULED, COMPLETED, CANCELLED"},
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
        limit = min(int(arguments.get("limit", 5)), 20)
        status = arguments.get("status")

        query: Dict[str, Any] = {"$or": [{"patient_id": caller_id}, {"user_id": caller_id}, {"doctor_id": caller_id}]}
        if status:
            query["status"] = status.upper()

        cursor = self.db.appointments.find(query).sort("appointment_date", -1).limit(limit)
        appts = await cursor.to_list(length=limit)

        clean_appts = [
            {
                "appointment_id": a.get("id"),
                "doctor_name": a.get("doctor_name") or a.get("doctor", {}).get("name", "Doctor"),
                "appointment_date": str(a.get("appointment_date") or a.get("slot_time")),
                "status": a.get("status", "SCHEDULED"),
                "fee": a.get("consultation_fee") or a.get("fee", 0.0),
            }
            for a in appts
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={"appointments": clean_appts, "total": len(clean_appts)},
            metadata={"action": "GET_MY_APPOINTMENTS", "user_id": caller_id},
        )
