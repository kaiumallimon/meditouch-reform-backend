from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.common.enums import DoctorVerificationStatus
from app.modules.doctors.schemas import DoctorVerificationDocSchema, DoctorProfileResponse

class CreateDoctorAccountRequest(BaseModel):
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=10)
    email: EmailStr = Field(..., description="Doctor email address where credentials will be delivered")
    password: Optional[str] = Field(default=None, description="Optional manual password. If omitted, a readable strong passphrase will be generated and emailed.")
    bmdc_reg_number: str = Field(..., min_length=3)
    specialties: List[str] = Field(default_factory=list)
    qualifications: List[str] = Field(default_factory=list)
    experience_years: int = 0
    consultation_fee: float = 0.0
    bio: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, description="Doctor profile picture Cloudinary URL")
    verification_documents: Optional[List[DoctorVerificationDocSchema]] = Field(default_factory=list)

class AdminUpdateDoctorRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2)
    phone: Optional[str] = Field(None, min_length=10)
    email: Optional[EmailStr] = None
    bmdc_reg_number: Optional[str] = Field(None, min_length=3)
    specialties: Optional[List[str]] = None
    qualifications: Optional[List[str]] = None
    experience_years: Optional[int] = None
    consultation_fee: Optional[float] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    verification_documents: Optional[List[DoctorVerificationDocSchema]] = None
    is_active: Optional[bool] = None
    verification_status: Optional[DoctorVerificationStatus] = None

class VerifyDoctorRequest(BaseModel):
    status: DoctorVerificationStatus
    rejection_reason: Optional[str] = None

class UpdateDoctorStatusRequest(BaseModel):
    is_active: bool

class AdminDashboardStats(BaseModel):
    total_users: int
    total_doctors: int
    active_doctors: int
    pending_doctor_verifications: int
    total_appointments: int
    completed_consultations: int
    total_orders: int
    total_revenue_bdt: float

class AuditLogEntry(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

