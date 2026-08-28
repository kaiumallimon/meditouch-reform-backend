from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.common.enums import DoctorVerificationStatus, TimeslotStatus

class DoctorVerificationDocSchema(BaseModel):
    document_type: str # BMDC_CERTIFICATE, NID, MEDICAL_DEGREE
    document_url: str
    uploaded_at: Optional[datetime] = None

class DoctorProfileResponse(BaseModel):
    id: str
    user_id: str
    name: str
    phone: str
    email: Optional[str] = None
    bmdc_reg_number: str
    specialties: List[str] = Field(default_factory=list)
    qualifications: List[str] = Field(default_factory=list)
    experience_years: int = 0
    bio: Optional[str] = None
    consultation_fee: float = 0.0
    is_verified: bool = False
    verification_status: DoctorVerificationStatus = DoctorVerificationStatus.PENDING
    is_active: bool = False
    rating: float = 5.0
    total_reviews: int = 0
    total_consultations: int = 0
    verification_documents: Optional[List[DoctorVerificationDocSchema]] = None

class UpdateDoctorProfileRequest(BaseModel):
    bio: Optional[str] = None
    specialties: Optional[List[str]] = None
    qualifications: Optional[List[str]] = None
    experience_years: Optional[int] = None
    consultation_fee: Optional[float] = Field(None, ge=0.0, description="Doctor consultation fee in BDT")

class CreateTimeslotRequest(BaseModel):
    start_time: datetime = Field(..., description="ISO 8601 UTC start datetime")
    end_time: datetime = Field(..., description="ISO 8601 UTC end datetime")

class BatchCreateTimeslotsRequest(BaseModel):
    slots: List[CreateTimeslotRequest]

class TimeslotResponse(BaseModel):
    id: str
    doctor_id: str
    start_time: datetime
    end_time: datetime
    status: TimeslotStatus
    created_at: Optional[datetime] = None

class DoctorFilterParams(BaseModel):
    specialty: Optional[str] = None
    search: Optional[str] = None
    min_fee: Optional[float] = None
    max_fee: Optional[float] = None

