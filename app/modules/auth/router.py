from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.auth.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    UserProfileResponse
)
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload

router = APIRouter(prefix="/auth", tags=["Authentication"])

def get_auth_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> AuthService:
    repo = AuthRepository(db)
    return AuthService(repo, db)

@router.post("/register", response_model=APIResponse[TokenResponse], status_code=status.HTTP_201_CREATED)
async def register(
    req: UserRegisterRequest,
    service: AuthService = Depends(get_auth_service)
):
    token_resp = await service.register_user(req)
    return APIResponse(
        success=True,
        message="User registered successfully",
        data=token_resp
    )

@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(
    req: UserLoginRequest,
    service: AuthService = Depends(get_auth_service)
):
    token_resp = await service.login(req)
    return APIResponse(
        success=True,
        message="Login successful",
        data=token_resp
    )

@router.post("/refresh", response_model=APIResponse[TokenResponse])
async def refresh_token(
    req: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service)
):
    token_resp = await service.refresh_tokens(req)
    return APIResponse(
        success=True,
        message="Token refreshed successfully",
        data=token_resp
    )

@router.get("/me", response_model=APIResponse[UserProfileResponse])
async def get_current_user_info(
    payload: dict = Depends(get_current_user_payload),
    service: AuthService = Depends(get_auth_service)
):
    profile = await service.get_user_profile(payload["sub"])
    return APIResponse(
        success=True,
        message="Profile retrieved",
        data=profile
    )

@router.post("/change-password", response_model=APIResponse[dict])
async def change_password(
    req: ChangePasswordRequest,
    payload: dict = Depends(get_current_user_payload),
    service: AuthService = Depends(get_auth_service)
):
    await service.change_password(payload["sub"], req)
    return APIResponse(
        success=True,
        message="Password changed successfully",
        data={"user_id": payload["sub"]}
    )

