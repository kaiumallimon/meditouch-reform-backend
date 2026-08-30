from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
import re

class EntityResolver:
    """
    Disambiguates natural language queries for users, doctors, and medicines.
    If multiple matches are found, it returns candidates instead of guessing.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def resolve_user(self, query: str) -> Dict[str, Any]:
        """
        Resolves a user by ID, phone number, email, or name.
        """
        clean = query.strip()
        # 1. Exact ID Match
        user = await self.db.users.find_one({"id": clean})
        if user:
            return {"status": "EXACT_MATCH", "match": user}

        # 2. Exact Phone Match
        user = await self.db.users.find_one({"phone": clean})
        if user:
            return {"status": "EXACT_MATCH", "match": user}

        # 3. Exact Email Match
        user = await self.db.users.find_one({"email": clean})
        if user:
            return {"status": "EXACT_MATCH", "match": user}

        # 4. Search by Name (Regex)
        regex = re.compile(re.escape(clean), re.IGNORECASE)
        cursor = self.db.users.find({"name": {"$regex": regex}, "is_deleted": {"$ne": True}}).limit(5)
        candidates = await cursor.to_list(length=5)

        if len(candidates) == 1:
            return {"status": "EXACT_MATCH", "match": candidates[0]}
        elif len(candidates) > 1:
            return {
                "status": "AMBIGUOUS",
                "candidates": [
                    {
                        "id": u.get("id"),
                        "name": u.get("name"),
                        "phone": u.get("phone"),
                        "email": u.get("email"),
                        "role": u.get("role"),
                    }
                    for u in candidates
                ],
            }
        return {"status": "NOT_FOUND"}

    async def resolve_doctor(self, query: str) -> Dict[str, Any]:
        """
        Resolves a doctor by ID, BMDC registration number, phone, email, or name.
        """
        clean = query.strip()
        # 1. Exact ID or BMDC Match
        doc = await self.db.doctors.find_one({"$or": [{"id": clean}, {"bmdc_reg_number": clean.upper()}]})
        if doc:
            return {"status": "EXACT_MATCH", "match": doc}

        # 2. Phone or Email Match
        doc = await self.db.doctors.find_one({"$or": [{"phone": clean}, {"email": clean}]})
        if doc:
            return {"status": "EXACT_MATCH", "match": doc}

        # 3. Name Regex Match
        regex = re.compile(re.escape(clean), re.IGNORECASE)
        cursor = self.db.doctors.find({"name": {"$regex": regex}, "is_deleted": {"$ne": True}}).limit(5)
        candidates = await cursor.to_list(length=5)

        if len(candidates) == 1:
            return {"status": "EXACT_MATCH", "match": candidates[0]}
        elif len(candidates) > 1:
            return {
                "status": "AMBIGUOUS",
                "candidates": [
                    {
                        "id": d.get("id"),
                        "name": d.get("name"),
                        "bmdc_reg_number": d.get("bmdc_reg_number"),
                        "specialties": d.get("specialties"),
                        "is_verified": d.get("is_verified", False),
                    }
                    for d in candidates
                ],
            }
        return {"status": "NOT_FOUND"}

    async def resolve_medicine(self, query: str) -> Dict[str, Any]:
        """
        Resolves a medicine by slug, ID, or brand name.
        """
        clean = query.strip()
        # 1. Exact slug or ID
        med = await self.db.medicines.find_one({"$or": [{"slug": clean}, {"id": clean}], "is_deleted": {"$ne": True}})
        if med:
            return {"status": "EXACT_MATCH", "match": med}

        # 2. Search by brand
        regex = re.compile(re.escape(clean), re.IGNORECASE)
        cursor = self.db.medicines.find({"brand": {"$regex": regex}, "is_deleted": {"$ne": True}}).limit(6)
        candidates = await cursor.to_list(length=6)

        if len(candidates) == 1:
            return {"status": "EXACT_MATCH", "match": candidates[0]}
        elif len(candidates) > 1:
            return {
                "status": "AMBIGUOUS",
                "candidates": [
                    {
                        "id": m.get("id"),
                        "slug": m.get("slug"),
                        "brand": m.get("brand"),
                        "generic_name": m.get("generic_name"),
                        "strength": m.get("strength"),
                        "unit_price": m.get("unit_price"),
                    }
                    for m in candidates
                ],
            }
        return {"status": "NOT_FOUND"}
