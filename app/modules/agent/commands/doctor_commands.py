from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from app.common.enums import DoctorVerificationStatus

class CreateDoctorCommand(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., min_length=10, max_length=20)
    email: EmailStr
    bmdc_number: str = Field(..., min_length=3)
    specialty: str = Field(..., min_length=2)
    degrees: List[str] = Field(default_factory=lambda: ["MBBS"])
    consultation_fee: float = Field(default=500.0, ge=0.0)
    hospital_affiliation: Optional[str] = None
    experience_years: int = Field(default=1, ge=0)
    bio: Optional[str] = None

class VerifyDoctorCommand(BaseModel):
    doctor_id: str = Field(..., min_length=1)
    status: DoctorVerificationStatus = Field(default=DoctorVerificationStatus.VERIFIED)
    notes: Optional[str] = "Verified via Admin AI Assistant"

class DeleteDoctorCommand(BaseModel):
    doctor_id: str = Field(..., min_length=1)
    reason: Optional[str] = "Doctor profile deleted via Admin AI Assistant"
