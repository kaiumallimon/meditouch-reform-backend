from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
import re
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.common.enums import UserRole

class SuggestMedicinesForSymptomsTool(BaseTool):
    name = "suggest_medicines_for_symptoms"
    description = "Searches approved Over-The-Counter (OTC) medicines matching specific mild symptoms."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    parameters = {
        "type": "object",
        "properties": {
            "symptom": {"type": "string", "description": "Mild symptom description (e.g. 'mild fever', 'headache', 'acid reflux')"},
        },
        "required": ["symptom"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        symptom = arguments.get("symptom", "").strip()
        if not symptom:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message="Symptom query is empty",
            )

        regex = re.compile(re.escape(symptom), re.IGNORECASE)
        # Search strictly for OTC medicines (requires_prescription: False)
        cursor = self.db.medicines.find({
            "requires_prescription": {"$ne": True},
            "is_active": {"$ne": False},
            "$or": [
                {"description": {"$regex": regex}},
                {"generic_name": {"$regex": regex}},
                {"brand": {"$regex": regex}},
                {"category": {"$regex": regex}},
            ]
        }).limit(4)

        matching_meds = await cursor.to_list(length=4)

        if not matching_meds:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={
                    "found": False,
                    "message": "No approved Over-The-Counter medication matched the described symptom.",
                    "disclaimer": "I cannot recommend a medication for these symptoms without a clinical evaluation. Please consult a licensed doctor.",
                }
            )

        results = [
            {
                "id": m.get("id"),
                "brand": m.get("brand") or m.get("name"),
                "generic_name": m.get("generic_name"),
                "strength": m.get("strength"),
                "dosage_form": m.get("dosage_form"),
                "unit_price": m.get("unit_price"),
                "description": m.get("description"),
                "in_stock": m.get("in_stock", True),
                "image": m.get("medicine_image"),
            }
            for m in matching_meds
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={
                "found": True,
                "otc_suggestions": results,
                "disclaimer": "This information is from MediTouch catalog records for approved OTC use. It is not personal medical advice. Consult a doctor or pharmacist before use.",
            },
            metadata={"count": len(results)},
        )
