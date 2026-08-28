from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.users.repository import UserManagementRepository
from app.modules.users.service import UserService
from app.modules.users.schemas import UserUpdateRequest, AddressSchema, UserDetailsResponse
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload

router = APIRouter(prefix="/users", tags=["Users"])

def get_user_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> UserService:
    repo = UserManagementRepository(db)
    return UserService(repo)

@router.get("/profile", response_model=APIResponse[UserDetailsResponse])
async def get_profile(
    payload: dict = Depends(get_current_user_payload),
    service: UserService = Depends(get_user_service)
):
    details = await service.get_user_details(payload["sub"])
    return APIResponse(success=True, message="Profile details retrieved", data=details)

@router.put("/profile", response_model=APIResponse[UserDetailsResponse])
async def update_profile(
    req: UserUpdateRequest,
    payload: dict = Depends(get_current_user_payload),
    service: UserService = Depends(get_user_service)
):
    details = await service.update_profile(payload["sub"], req)
    return APIResponse(success=True, message="Profile updated successfully", data=details)

@router.post("/addresses", response_model=APIResponse[list[AddressSchema]], status_code=status.HTTP_201_CREATED)
async def add_address(
    req: AddressSchema,
    payload: dict = Depends(get_current_user_payload),
    service: UserService = Depends(get_user_service)
):
    addresses = await service.add_address(payload["sub"], req)
    return APIResponse(success=True, message="Address added successfully", data=addresses)

