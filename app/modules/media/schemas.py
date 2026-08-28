from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

class MediaFolder(str, Enum):
    GENERAL = "meditouch/general"
    PROFILES = "meditouch/profiles"
    DOCTORS_DOCUMENTS = "meditouch/doctors/documents"
    PRESCRIPTIONS = "meditouch/prescriptions"
    MEDICINES = "meditouch/medicines"

class MediaUploadResponse(BaseModel):
    public_id: str
    secure_url: str
    url: str
    format: str
    resource_type: str
    bytes: int
    original_filename: str
    folder: str
    created_at: Optional[str] = None

class MultipleMediaUploadResponse(BaseModel):
    files: List[MediaUploadResponse]
    total_files: int

