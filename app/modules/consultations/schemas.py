from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class VideoRoomTokenResponse(BaseModel):
    appointment_id: str
    room_id: str
    user_id: str
    user_name: str
    app_id: int
    zego_token: str
    expires_in_seconds: int

class PrescribedMedicationSchema(BaseModel):
    medicine_name: str
    dosage: str # e.g. 500mg
    frequency: str # e.g. 1+0+1 (morning and night)
    duration_days: int
    instructions: Optional[str] = "After meals"

class CompleteConsultationRequest(BaseModel):
    diagnosis: str = Field(..., min_length=2)
    clinical_notes: Optional[str] = None
    prescriptions: List[PrescribedMedicationSchema] = Field(default_factory=list)
    follow_up_date: Optional[str] = None
    advice: Optional[str] = None

class ConsultationRecordResponse(BaseModel):
    id: str
    appointment_id: str
    patient_id: str
    patient_name: str
    doctor_id: str
    doctor_name: str
    diagnosis: str
    clinical_notes: Optional[str] = None
    prescriptions: List[PrescribedMedicationSchema] = Field(default_factory=list)
    follow_up_date: Optional[str] = None
    advice: Optional[str] = None
    completed_at: datetime

