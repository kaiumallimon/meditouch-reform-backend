from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum

class MediaFolder(str, Enum):
    GENERAL = "meditouch/general"
    PROFILES = "meditouch/profiles"
    DOCTORS_DOCUMENTS = "meditouch/doctors/documents"
    PRESCRIPTIONS = "meditouch/prescriptions"
    MEDICINES = "meditouch/medicines"

class MediaUploadResponse(BaseModel):
    id: Optional[str] = None
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

class MediaAssetResponse(BaseModel):
    id: str
    public_id: str
    secure_url: str
    url: str
    format: str
    resource_type: str
    bytes: int
    original_filename: str
    folder: str
    uploader_id: Optional[str] = None
    created_at: Optional[str] = None

class MediaFolderStat(BaseModel):
    folder: str
    count: int
    bytes: int

class MediaCDNStatsResponse(BaseModel):
    total_assets: int
    total_bytes: int
    total_images: int
    total_documents: int
    storage_used_formatted: str
    cloud_name: str
    is_configured: bool
    folders: List[MediaFolderStat]
