from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
import re
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.common.enums import UserRole

SYMPTOM_GENERIC_MAP = {
    "headache": ["Paracetamol", "Ibuprofen", "Naproxen", "Aspirin"],
    "migraine": ["Paracetamol", "Ibuprofen", "Naproxen"],
    "fever": ["Paracetamol", "Ibuprofen"],
    "pain": ["Paracetamol", "Ibuprofen", "Naproxen"],
    "body ache": ["Paracetamol", "Ibuprofen"],
    "back pain": ["Ibuprofen", "Paracetamol", "Naproxen"],
    "toothache": ["Paracetamol", "Ibuprofen"],
    "sore throat": ["Paracetamol", "Strepsils", "Povidone-Iodine"],
    "gastric": ["Esomeprazole", "Omeprazole", "Pantoprazole", "Famotidine", "Antacid"],
    "acidity": ["Esomeprazole", "Omeprazole", "Pantoprazole", "Famotidine", "Antacid"],
    "heartburn": ["Esomeprazole", "Omeprazole", "Pantoprazole", "Famotidine", "Antacid"],
    "acid reflux": ["Esomeprazole", "Omeprazole", "Pantoprazole", "Famotidine", "Antacid"],
    "indigestion": ["Esomeprazole", "Omeprazole", "Famotidine", "Antacid"],
    "cold": ["Fexofenadine", "Cetirizine", "Loratadine", "Montelukast", "Paracetamol"],
    "cough": ["Dextromethorphan", "Montelukast", "Fexofenadine", "Bromhexine"],
    "flu": ["Paracetamol", "Fexofenadine", "Cetirizine"],
    "runny nose": ["Fexofenadine", "Cetirizine", "Loratadine"],
    "sneezing": ["Fexofenadine", "Cetirizine", "Loratadine"],
    "allergy": ["Fexofenadine", "Cetirizine", "Loratadine", "Montelukast"],
    "itch": ["Fexofenadine", "Cetirizine", "Loratadine"],
    "vomiting": ["Domperidone", "Ondansetron"],
    "nausea": ["Domperidone", "Ondansetron"],
    "diarrhea": ["Oral Rehydration Salts", "ORS", "Zinc"],
    "saline": ["Oral Rehydration Salts", "ORS"],
    "weakness": ["Vitamin B1 + B6 + B12", "Ascorbic acid", "Vitamin C"],
    "fatigue": ["Vitamin B1 + B6 + B12", "Ascorbic acid", "Vitamin C"],
}

class SuggestMedicinesForSymptomsTool(BaseTool):
    name = "suggest_medicines_for_symptoms"
    description = "Searches approved Over-The-Counter (OTC) medicines matching specific mild symptoms like headache, fever, acidity, cold, cough, or pain."
    roles_allowed = [UserRole.USER.value, UserRole.DOCTOR.value, UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    parameters = {
        "type": "object",
        "properties": {
            "symptom": {"type": "string", "description": "Symptom description (e.g. 'headache', 'mild fever', 'acidity', 'cold', 'body pain')"},
        },
        "required": ["symptom"],
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        symptom_text = arguments.get("symptom", "").lower().strip()
        if not symptom_text:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.ERROR,
                result=None,
                error_message="Symptom query is empty",
            )

        # 1. Identify Target Generics from Clinical Ontology
        matched_generics = []
        for key, generics in SYMPTOM_GENERIC_MAP.items():
            if key in symptom_text:
                matched_generics.extend(generics)

        # Deduplicate generics
        matched_generics = list(dict.fromkeys(matched_generics))

        or_conditions = []
        for gen in matched_generics:
            or_conditions.append({"generic_name": {"$regex": re.escape(gen), "$options": "i"}})

        # Fallback keyword regex
        clean_kw = re.sub(r"[^a-zA-Z0-9\s]", "", symptom_text)
        for word in clean_kw.split():
            if len(word) > 3 and word not in ["have", "having", "severe", "mild", "what", "pills", "take", "should", "some", "with"]:
                or_conditions.append({"generic_name": {"$regex": re.escape(word), "$options": "i"}})
                or_conditions.append({"brand": {"$regex": re.escape(word), "$options": "i"}})
                or_conditions.append({"name": {"$regex": re.escape(word), "$options": "i"}})

        if not or_conditions:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={
                    "found": False,
                    "message": f"No approved Over-The-Counter medication matched symptom '{symptom_text}'.",
                    "disclaimer": "Please consult a registered physician for clinical diagnosis.",
                },
            )

        # Strictly query PHARMACEUTICAL medicines (exclude cosmetics / skin care)
        query = {
            "is_active": {"$ne": False},
            "category": {"$nin": ["SKIN_CARE", "COSMETICS", "BEAUTY", "SKIN CARE", "Skin Care"]},
            "category_slug": {"$nin": ["skin-care", "cosmetics", "beauty"]},
            "$or": or_conditions,
        }

        cursor = self.db.medicines.find(query).limit(5)
        matching_meds = await cursor.to_list(length=5)

        if not matching_meds:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                status=ToolExecutionStatus.SUCCESS,
                result={
                    "found": False,
                    "message": "No approved Over-The-Counter medication found in stock for these symptoms.",
                    "disclaimer": "Please consult a licensed doctor for proper evaluation.",
                },
            )

        results = [
            {
                "id": str(m.get("id") or m.get("_id")),
                "brand": m.get("brand") or m.get("name"),
                "generic_name": m.get("generic_name"),
                "strength": m.get("strength"),
                "dosage_form": m.get("dosage_form") or m.get("category_name", "Tablet"),
                "unit_price": m.get("unit_price"),
                "in_stock": m.get("in_stock", True),
                "stock_count": m.get("stock_count", 100),
                "image": m.get("medicine_image"),
                "manufacturer": m.get("manufacturer") or m.get("manufacturer_name", "Pharma"),
            }
            for m in matching_meds
        ]

        is_severe = any(w in symptom_text for w in ["severe", "extreme", "unbearable", "worst", "chest pain", "emergency"])

        disclaimer = "⚠️ **Important Clinical Notice**: This guidance is for mild, common symptoms only. "
        if is_severe:
            disclaimer += "**Since you described this as severe, please seek immediate medical attention or consult a doctor promptly.**"
        else:
            disclaimer += "Always read the product leaflet. Consult a doctor or pharmacist if symptoms persist beyond 3 days."

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={
                "found": True,
                "symptom": symptom_text,
                "otc_suggestions": results,
                "disclaimer": disclaimer,
            },
            metadata={"count": len(results), "symptom": symptom_text},
        )
