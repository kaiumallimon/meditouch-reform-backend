from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any

class AddressSchema(BaseModel):
    id: Optional[str] = None
    label: str = "Home" # Home, Office, Other
    recipient_name: str
    recipient_phone: str
    division: str
    district: str
    upazila_or_thana: str
    street_address: str
    is_default: bool = False

class MedicalProfileSchema(BaseModel):
    blood_group: Optional[str] = None
    allergies: List[str] = Field(default_factory=list)
    chronic_conditions: List[str] = Field(default_factory=list)
    current_medications: List[str] = Field(default_factory=list)
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    medical_profile: Optional[MedicalProfileSchema] = None

class UserDetailsResponse(BaseModel):
    id: str
    name: str
    phone: str
    email: Optional[str] = None
    role: str
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    addresses: List[AddressSchema] = Field(default_factory=list)
    medical_profile: Optional[MedicalProfileSchema] = None

