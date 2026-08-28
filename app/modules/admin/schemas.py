from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.common.enums import DoctorVerificationStatus
from app.modules.doctors.schemas import DoctorVerificationDocSchema, DoctorProfileResponse

class CreateDoctorAccountRequest(BaseModel):
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=10)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=6)
    bmdc_reg_number: str = Field(..., min_length=3)
    specialties: List[str] = Field(default_factory=list)
    qualifications: List[str] = Field(default_factory=list)
    experience_years: int = 0
    consultation_fee: float = 0.0
    bio: Optional[str] = None
    verification_documents: Optional[List[DoctorVerificationDocSchema]] = Field(default_factory=list)

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

