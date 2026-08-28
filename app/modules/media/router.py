from fastapi import APIRouter, Depends, UploadFile, File, Form, status, Query
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import uuid
import re

from app.db.mongodb import get_db
from app.modules.media.schemas import (
    MediaUploadResponse,
    MultipleMediaUploadResponse,
    MediaFolder,
    MediaAssetResponse,
    MediaCDNStatsResponse,
    MediaFolderStat
)
from app.integrations.cloudinary.client import cloudinary_service
from app.common.responses import APIResponse
from app.common.enums import AuditAction, UserRole
from app.common.pagination import PaginationParams, PaginatedResponse
from app.core.security import get_current_user_payload
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from app.core.logging import log_audit_event

router = APIRouter(prefix="/media", tags=["Media & Cloudinary CDN"])

def format_storage_bytes(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"

async def record_asset(db: AsyncIOMotorDatabase, res: Dict[str, Any], uploader_id: Optional[str] = None) -> Dict[str, Any]:
    asset_id = str(uuid.uuid4())
    doc = {
        "id": asset_id,
        "public_id": res["public_id"],
        "secure_url": res["secure_url"],
        "url": res["url"],
        "format": res["format"],
        "resource_type": res["resource_type"],
        "bytes": res["bytes"],
        "original_filename": res["original_filename"],
        "folder": res["folder"],
        "uploader_id": uploader_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.media_assets.insert_one(doc)
    return doc

@router.post("/upload", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    folder: MediaFolder = Form(default=MediaFolder.GENERAL),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Uploads a single image or document to Cloudinary CDN and records asset.
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

    doc = await record_asset(db, res, payload.get("sub"))

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
        data=MediaUploadResponse(id=doc["id"], **res)
    )

@router.post("/upload-multiple", response_model=APIResponse[MultipleMediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    folder: MediaFolder = Form(default=MediaFolder.GENERAL),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Uploads multiple files (up to 10) to Cloudinary CDN in batch.
    """
    if not files:
        raise BadRequestException("No files provided")
    if len(files) > 10:
        raise BadRequestException("Maximum 10 files can be uploaded concurrently")

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
        doc = await record_asset(db, res, payload.get("sub"))
        uploaded.append(MediaUploadResponse(id=doc["id"], **res))

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
    if not file.filename:
        raise BadRequestException("File name is missing")

    contents = await file.read()
    res = await cloudinary_service.upload_file(
        file_bytes=contents,
        filename=file.filename,
        folder=MediaFolder.PRESCRIPTIONS.value,
        tags=[payload.get("sub", "user"), "prescription"]
    )
    doc = await record_asset(db, res, payload.get("sub"))

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
        data=MediaUploadResponse(id=doc["id"], **res)
    )

@router.post("/doctor-document", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_doctor_document(
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    if not file.filename:
        raise BadRequestException("File name is missing")

    contents = await file.read()
    res = await cloudinary_service.upload_file(
        file_bytes=contents,
        filename=file.filename,
        folder=MediaFolder.DOCTORS_DOCUMENTS.value,
        tags=[payload.get("sub", "user"), "doctor_doc"]
    )
    doc = await record_asset(db, res, payload.get("sub"))

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
        data=MediaUploadResponse(id=doc["id"], **res)
    )

@router.post("/avatar", response_model=APIResponse[MediaUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_avatar(
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
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
    doc = await record_asset(db, res, payload.get("sub"))

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
        data=MediaUploadResponse(id=doc["id"], **res)
    )

@router.get("/assets", response_model=APIResponse[PaginatedResponse[MediaAssetResponse]])
async def list_media_assets(
    folder: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Lists paginated CDN media assets with folder, type, and search filters.
    """
    query: Dict[str, Any] = {}
    if folder:
        query["folder"] = folder
    if resource_type:
        query["resource_type"] = resource_type
    if search and search.strip():
        search_regex = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [
            {"original_filename": search_regex},
            {"public_id": search_regex},
            {"folder": search_regex},
            {"format": search_regex}
        ]

    pagination = PaginationParams(page=page, limit=limit)
    total = await db.media_assets.count_documents(query)
    cursor = db.media_assets.find(query).skip(pagination.skip).limit(pagination.limit).sort("created_at", -1)
    items_raw = await cursor.to_list(length=pagination.limit)
    items = [MediaAssetResponse(**d) for d in items_raw]

    return APIResponse(
        success=True,
        message="CDN media assets retrieved",
        data=PaginatedResponse.create(items=items, total=total, params=pagination)
    )

@router.get("/stats", response_model=APIResponse[MediaCDNStatsResponse])
async def get_cdn_stats(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Returns independent CDN storage stats and folder breakdowns.
    """
    total_assets = await db.media_assets.count_documents({})
    total_images = await db.media_assets.count_documents({"resource_type": "image"})
    total_documents = await db.media_assets.count_documents({"resource_type": {"$ne": "image"}})

    pipeline = [
        {"$group": {"_id": None, "total_bytes": {"$sum": "$bytes"}}}
    ]
    bytes_res = await db.media_assets.aggregate(pipeline).to_list(1)
    total_bytes = bytes_res[0]["total_bytes"] if bytes_res else 0

    folder_pipeline = [
        {"$group": {"_id": "$folder", "count": {"$sum": 1}, "bytes": {"$sum": "$bytes"}}},
        {"$sort": {"count": -1}}
    ]
    folder_res = await db.media_assets.aggregate(folder_pipeline).to_list(20)
    folder_stats = [
        MediaFolderStat(
            folder=f["_id"] or "meditouch/general",
            count=f["count"],
            bytes=f["bytes"]
        )
        for f in folder_res
    ]

    from app.core.config import settings
    cloud_name = settings.CLOUDINARY_CLOUD_NAME or "meditouch-cdn"

    return APIResponse(
        success=True,
        message="CDN statistics retrieved",
        data=MediaCDNStatsResponse(
            total_assets=total_assets,
            total_bytes=total_bytes,
            total_images=total_images,
            total_documents=total_documents,
            storage_used_formatted=format_storage_bytes(total_bytes),
            cloud_name=cloud_name,
            is_configured=cloudinary_service.is_configured,
            folders=folder_stats
        )
    )

@router.delete("/assets/{asset_id}", response_model=APIResponse[dict])
async def delete_media_asset(
    asset_id: str,
    payload: dict = Depends(get_current_user_payload),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Deletes an asset from Cloudinary CDN and removes record from database.
    Requires ADMIN or OWNER.
    """
    doc = await db.media_assets.find_one({"id": asset_id})
    if not doc:
        # Fallback search by public_id or _id
        doc = await db.media_assets.find_one({"public_id": asset_id})
    if not doc:
        raise NotFoundException("Media asset not found")

    is_admin = payload.get("role") == UserRole.ADMIN.value
    is_owner = doc.get("uploader_id") == payload.get("sub")
    if not (is_admin or is_owner):
        raise ForbiddenException("Permission denied to delete this asset")

    # Delete from Cloudinary CDN
    await cloudinary_service.delete_file(
        public_id=doc.get("public_id"),
        resource_type=doc.get("resource_type", "image")
    )

    # Delete from database
    await db.media_assets.delete_one({"id": doc["id"]})

    await log_audit_event(
        db,
        user_id=payload.get("sub"),
        action=AuditAction.MEDIA_DELETED,
        target_type="MEDIA",
        target_id=doc.get("public_id"),
        details={"filename": doc.get("original_filename"), "folder": doc.get("folder")}
    )

    return APIResponse(
        success=True,
        message="Media asset deleted from Cloudinary CDN and database",
        data={"id": doc["id"], "public_id": doc["public_id"]}
    )

@router.get("/stream")
async def stream_media_asset(
    url: str = Query(..., description="Cloudinary asset URL to stream or view"),
    filename: Optional[str] = Query(None, description="Optional download filename"),
    download: bool = Query(False, description="Whether to force download vs inline view")
):
    """
    Secure media streaming proxy that fetches from Cloudinary and returns with proper Content-Type
    and headers so that PDFs and documents view and download flawlessly without Cloudinary ACL 401s.
    """
    import httpx
    from fastapi.responses import Response

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            
            # If Cloudinary returned 401 on a PDF raw URL, fetch as image transformation (.png)
            if resp.status_code == 401 and url.lower().endswith(".pdf"):
                alt_url = url.replace("/raw/upload/", "/image/upload/").rsplit(".", 1)[0] + ".png"
                alt_resp = await client.get(alt_url)
                if alt_resp.status_code == 200:
                    resp = alt_resp

        content_type = resp.headers.get("content-type", "application/octet-stream")
        if url.lower().endswith(".pdf") and content_type == "application/octet-stream":
            content_type = "application/pdf"
        elif url.lower().endswith(".png"):
            content_type = "image/png"
        elif url.lower().endswith(".jpg") or url.lower().endswith(".jpeg"):
            content_type = "image/jpeg"

        disposition_type = "attachment" if download else "inline"
        out_name = filename or url.split("/")[-1] or "document.pdf"
        if not out_name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".doc")):
            if "pdf" in content_type:
                out_name += ".pdf"
            elif "png" in content_type:
                out_name += ".png"
            elif "jpeg" in content_type:
                out_name += ".jpg"

        headers = {
            "Content-Disposition": f'{disposition_type}; filename="{out_name}"',
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400"
        }
        return Response(content=resp.content, media_type=content_type, headers=headers)
    except Exception as e:
        raise BadRequestException(f"Failed to stream media: {str(e)}")

