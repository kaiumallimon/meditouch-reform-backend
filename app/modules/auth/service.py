from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    UserProfileResponse
)
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token
)
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    UnauthorizedException,
    NotFoundException
)
from app.common.enums import UserRole
from app.common.utils import sanitize_phone_number

class AuthService:
    def __init__(self, repo: AuthRepository):
        self.repo = repo

    async def register_user(self, req: UserRegisterRequest) -> TokenResponse:
        clean_phone = sanitize_phone_number(req.phone)
        
        # Check phone uniqueness
        existing_phone = await self.repo.get_by_phone(clean_phone)
        if existing_phone:
            raise ConflictException("A user with this phone number already exists")

        # Check email uniqueness if provided
        if req.email:
            existing_email = await self.repo.get_by_email(req.email)
            if existing_email:
                raise ConflictException("A user with this email already exists")

        hashed_pwd = hash_password(req.password)
        user_doc = {
            "name": req.name.strip(),
            "phone": clean_phone,
            "email": req.email.lower() if req.email else None,
            "hashed_password": hashed_pwd,
            "role": UserRole.USER.value,
            "is_active": True,
            "gender": req.gender,
            "date_of_birth": req.date_of_birth,
            "address": req.address,
        }

        created = await self.repo.create_user(user_doc)
        token_payload = {
            "sub": created["id"],
            "role": created["role"],
            "phone": created["phone"],
            "name": created["name"]
        }

        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=created["id"],
            role=UserRole(created["role"]),
            name=created["name"],
            phone=created["phone"],
            email=created.get("email")
        )

    async def login(self, req: UserLoginRequest) -> TokenResponse:
        identifier = req.identifier.strip()
        user = await self.repo.get_by_identifier(identifier)
        if not user:
            clean_phone = sanitize_phone_number(identifier)
            user = await self.repo.get_by_phone(clean_phone)

        if not user:
            raise UnauthorizedException("Invalid phone/email or password")

        if not verify_password(req.password, user.get("hashed_password", "")):
            raise UnauthorizedException("Invalid phone/email or password")

        if not user.get("is_active", True):
            raise UnauthorizedException("This account is inactive. Please contact support.")

        token_payload = {
            "sub": user["id"],
            "role": user["role"],
            "phone": user["phone"],
            "name": user["name"]
        }

        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user["id"],
            role=UserRole(user["role"]),
            name=user["name"],
            phone=user["phone"],
            email=user.get("email")
        )

    async def refresh_tokens(self, req: RefreshTokenRequest) -> TokenResponse:
        payload = decode_token(req.refresh_token, is_refresh=True)
        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedException("Invalid token payload")

        is_revoked = await self.repo.is_token_revoked(req.refresh_token)
        if is_revoked:
            raise UnauthorizedException("This refresh token has been revoked")

        user = await self.repo.get_by_id(user_id)
        if not user or not user.get("is_active", True):
            raise UnauthorizedException("User no longer exists or is inactive")

        token_payload = {
            "sub": user["id"],
            "role": user["role"],
            "phone": user["phone"],
            "name": user["name"]
        }

        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user["id"],
            role=UserRole(user["role"]),
            name=user["name"],
            phone=user["phone"],
            email=user.get("email")
        )

    async def change_password(self, user_id: str, req: ChangePasswordRequest) -> bool:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User not found")

        if not verify_password(req.current_password, user.get("hashed_password", "")):
            raise BadRequestException("Current password does not match")

        new_hashed = hash_password(req.new_password)
        return await self.repo.update_password(user_id, new_hashed)

    async def get_user_profile(self, user_id: str) -> UserProfileResponse:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User not found")

        return UserProfileResponse(
            id=user["id"],
            name=user["name"],
            phone=user["phone"],
            email=user.get("email"),
            role=UserRole(user["role"]),
            is_active=user.get("is_active", True),
            gender=user.get("gender"),
            date_of_birth=user.get("date_of_birth"),
            address=user.get("address"),
            created_at=str(user.get("created_at")) if user.get("created_at") else None
        )

