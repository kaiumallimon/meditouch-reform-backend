from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.users.repository import UserManagementRepository
from app.modules.users.schemas import UserUpdateRequest, AddressSchema, UserDetailsResponse, MedicalProfileSchema
from app.core.exceptions import NotFoundException
from app.common.enums import AuditAction
from app.core.logging import log_audit_event

class UserService:
    def __init__(self, repo: UserManagementRepository, db: Optional[AsyncIOMotorDatabase] = None):
        self.repo = repo
        self.db = db if db is not None else repo.db

    async def get_user_details(self, user_id: str) -> UserDetailsResponse:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User not found")

        med_profile = user.get("medical_profile")
        med_schema = MedicalProfileSchema(**med_profile) if med_profile else None
        
        addresses = [AddressSchema(**addr) for addr in user.get("addresses", [])]

        return UserDetailsResponse(
            id=user["id"],
            name=user["name"],
            phone=user["phone"],
            email=user.get("email"),
            role=user["role"],
            gender=user.get("gender"),
            date_of_birth=user.get("date_of_birth"),
            address=user.get("address"),
            addresses=addresses,
            medical_profile=med_schema
        )

    async def update_profile(self, user_id: str, req: UserUpdateRequest) -> UserDetailsResponse:
        updates = {}
        if req.name is not None:
            updates["name"] = req.name
        if req.email is not None:
            updates["email"] = req.email.lower()
        if req.gender is not None:
            updates["gender"] = req.gender
        if req.date_of_birth is not None:
            updates["date_of_birth"] = req.date_of_birth
        if req.address is not None:
            updates["address"] = req.address
        if req.medical_profile is not None:
            updates["medical_profile"] = req.medical_profile.model_dump()

        updated_user = await self.repo.update_profile(user_id, updates)
        if not updated_user:
            raise NotFoundException("User not found")

        await log_audit_event(
            self.db,
            user_id=user_id,
            action=AuditAction.USER_PROFILE_UPDATED,
            target_type="USER",
            target_id=user_id,
            details={"updated_fields": list(updates.keys())}
        )

        return await self.get_user_details(user_id)

    async def get_addresses(self, user_id: str) -> list[AddressSchema]:
        addresses = await self.repo.get_addresses(user_id)
        return [AddressSchema(**a) for a in addresses]

    async def add_address(self, user_id: str, address_req: AddressSchema) -> list[AddressSchema]:
        addresses = await self.repo.add_address(user_id, address_req.model_dump())
        return [AddressSchema(**a) for a in addresses]

    async def delete_address(self, user_id: str, address_id: str) -> list[AddressSchema]:
        addresses = await self.repo.delete_address(user_id, address_id)
        return [AddressSchema(**a) for a in addresses]
