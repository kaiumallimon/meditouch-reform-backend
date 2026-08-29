from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from app.common.enums import UserRole

class CreateUserCommand(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., min_length=10, max_length=20)
    email: Optional[EmailStr] = None
    role: UserRole = Field(default=UserRole.USER)
    gender: Optional[str] = "unspecified"
    address: Optional[str] = None

class DeactivateUserCommand(BaseModel):
    user_id: str = Field(..., min_length=1)
    reason: Optional[str] = "Deactivated via Admin AI Assistant"

class DeleteUserCommand(BaseModel):
    user_id: str = Field(..., min_length=1)
    reason: Optional[str] = "Deleted via Admin AI Assistant"
