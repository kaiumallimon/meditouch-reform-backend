from fastapi import APIRouter, Depends, UploadFile, File, Form, status, Query
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.media.schemas import MediaUploadResponse, MultipleMediaUploadResponse, MediaFolder
from app.integrations.cloudinary.client import cloudinary_service
from app.common.responses import APIResponse
from app.common.enums import AuditAction
from app.core.security import get_current_user_payload
from app.core.exceptions import BadRequestException
from app.core.logging import log_audit_event

router = APIRouter(prefix="/media", tags=["Media & Cloudinary CDN"])

@router.post("/upload", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    folder: MediaFolder = Form(default=MediaFolder.GENERAL),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Uploads a single image or document to Cloudinary CDN.
    Supports JPG, PNG, WEBP, GIF, SVG, PDF, DOC, DOCX.
    """
    if not file.filename:
        raise BadRequestException("File name is missing")

    contents = await file.read()
    if not contents:
        raise BadRequestException("Uploaded file is empty")

    res = await cloudinary_service.upload_file(
        file_bytes=contents,
        filename=file.filename,
        folder=folder.value,
        tags=[payload.get("sub", "user"), folder.name.lower()]
    )

    await log_audit_event(
        db,
        user_id=payload.get("sub"),
        action=AuditAction.MEDIA_UPLOADED,
        target_type="MEDIA",
        target_id=res.get("public_id"),
        details={"filename": file.filename, "folder": folder.value, "size_bytes": len(contents)}
    )

    return APIResponse(
        success=True,
        message="File uploaded to Cloudinary CDN successfully",
        data=MediaUploadResponse(**res)
    )

@router.post("/upload-multiple", response_model=APIResponse[MultipleMediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    folder: MediaFolder = Form(default=MediaFolder.GENERAL),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Uploads multiple files (up to 5) to Cloudinary CDN in batch.
    """
    if not files:
        raise BadRequestException("No files provided")
    if len(files) > 5:
        raise BadRequestException("Maximum 5 files can be uploaded concurrently")

    uploaded = []
    for f in files:
        if not f.filename:
            continue
        contents = await f.read()
        if not contents:
            continue
        res = await cloudinary_service.upload_file(
            file_bytes=contents,
            filename=f.filename,
            folder=folder.value,
            tags=[payload.get("sub", "user"), folder.name.lower()]
        )
        uploaded.append(MediaUploadResponse(**res))

    await log_audit_event(
        db,
        user_id=payload.get("sub"),
        action=AuditAction.MEDIA_UPLOADED,
        target_type="MEDIA",
        target_id=f"{len(uploaded)}_files",
        details={"folder": folder.value, "total_files": len(uploaded)}
    )

    return APIResponse(
        success=True,
        message=f"{len(uploaded)} file(s) uploaded to Cloudinary CDN successfully",
        data=MultipleMediaUploadResponse(files=uploaded, total_files=len(uploaded))
    )

@router.post("/prescription", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_prescription(
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Dedicated endpoint for patients uploading prescription images/PDFs.
    """
    if not file.filename:
        raise BadRequestException("File name is missing")

    contents = await file.read()
    res = await cloudinary_service.upload_file(
        file_bytes=contents,
        filename=file.filename,
        folder=MediaFolder.PRESCRIPTIONS.value,
        tags=[payload.get("sub", "user"), "prescription"]
    )

    await log_audit_event(
        db,
        user_id=payload.get("sub"),
        action=AuditAction.MEDIA_UPLOADED,
        target_type="PRESCRIPTION_MEDIA",
        target_id=res.get("public_id"),
        details={"filename": file.filename}
    )

    return APIResponse(
        success=True,
        message="Prescription uploaded to CDN successfully",
        data=MediaUploadResponse(**res)
    )

@router.post("/doctor-document", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_doctor_document(
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Dedicated endpoint for uploading doctor verification credentials (BMDC Certificate, NID, Medical Degree).
    """
    if not file.filename:
        raise BadRequestException("File name is missing")

    contents = await file.read()
    res = await cloudinary_service.upload_file(
        file_bytes=contents,
        filename=file.filename,
        folder=MediaFolder.DOCTORS_DOCUMENTS.value,
        tags=[payload.get("sub", "user"), "doctor_doc"]
    )

    await log_audit_event(
        db,
        user_id=payload.get("sub"),
        action=AuditAction.MEDIA_UPLOADED,
        target_type="DOCTOR_DOC_MEDIA",
        target_id=res.get("public_id"),
        details={"filename": file.filename}
    )

    return APIResponse(
        success=True,
        message="Doctor verification document uploaded to CDN successfully",
        data=MediaUploadResponse(**res)
    )

@router.post("/avatar", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_avatar(
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Dedicated endpoint for uploading doctor and patient profile avatars to Cloudinary CDN.
    """
    if not file.filename:
        raise BadRequestException("File name is missing")

    contents = await file.read()
    if not contents:
        raise BadRequestException("Uploaded image is empty")

    res = await cloudinary_service.upload_file(
        file_bytes=contents,
        filename=file.filename,
        folder=MediaFolder.PROFILES.value,
        tags=[payload.get("sub", "user"), "avatar", "profile_picture"]
    )

    await log_audit_event(
        db,
        user_id=payload.get("sub"),
        action=AuditAction.MEDIA_UPLOADED,
        target_type="AVATAR_MEDIA",
        target_id=res.get("public_id"),
        details={"filename": file.filename}
    )

    return APIResponse(
        success=True,
        message="Doctor profile picture uploaded to CDN successfully",
        data=MediaUploadResponse(**res)
    )

