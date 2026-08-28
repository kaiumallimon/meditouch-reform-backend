from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.common.enums import UserRole

class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., min_length=10, max_length=20)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=6)
    gender: Optional[str] = "unspecified"
    date_of_birth: Optional[str] = None
    address: Optional[str] = None

class UserLoginRequest(BaseModel):
    identifier: str = Field(..., description="Phone number or email")
    password: str = Field(...)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    role: UserRole
    name: str
    phone: str
    email: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

class UserProfileResponse(BaseModel):
    id: str
    name: str
    phone: str
    email: Optional[str] = None
    role: UserRole
    is_active: bool
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    created_at: Optional[str] = None

