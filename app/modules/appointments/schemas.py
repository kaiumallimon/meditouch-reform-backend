from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.common.enums import AppointmentStatus

class BookAppointmentRequest(BaseModel):
    doctor_id: str
    timeslot_id: str
    patient_notes: Optional[str] = None
    symptoms: Optional[List[str]] = Field(default_factory=list)

class FeeBreakdownResponse(BaseModel):
    doctor_fee: float
    platform_fee: float
    platform_fee_percent: float
    total_amount: float
    currency: str = "BDT"

class AppointmentResponse(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    patient_phone: str
    doctor_id: str
    doctor_name: str
    doctor_specialties: List[str] = Field(default_factory=list)
    timeslot_id: str
    start_time: datetime
    end_time: datetime
    doctor_fee: float
    platform_fee: float
    total_amount: float
    status: AppointmentStatus
    payment_id: Optional[str] = None
    merchant_invoice_number: Optional[str] = None
    payment_url: Optional[str] = None
    patient_notes: Optional[str] = None
    symptoms: List[str] = Field(default_factory=list)
    is_joinable: bool = False
    created_at: Optional[datetime] = None

