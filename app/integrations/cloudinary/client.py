import os
import uuid
import time
import re
from typing import Optional, Dict, Any, Union
import cloudinary
import cloudinary.uploader
import cloudinary.api
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import BadRequestException

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
ALLOWED_ALL_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_DOCUMENT_EXTENSIONS

# Max file sizes
MAX_IMAGE_SIZE_BYTES = 500 * 1024             # 500 KB (for profile picture / avatar / images)
MAX_DOCUMENT_SIZE_BYTES = 1 * 1024 * 1024      # 1 MB (for uploaded PDF / doctor documents)

class CloudinaryCDNService:
    def __init__(self):
        self.is_configured = False
        self._configure()

    def _configure(self):
        if settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET:
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
                secure=settings.CLOUDINARY_SECURE
            )
            self.is_configured = True
            logger.info(f"Cloudinary configured for cloud_name: {settings.CLOUDINARY_CLOUD_NAME}")
        else:
            self.is_configured = False
            logger.warning("Cloudinary credentials not fully provided. CDN service running in development simulation mode.")

    def validate_file(self, filename: str, file_bytes: bytes) -> str:
        """
        Validates file extension and size. Returns resource_type ('image' or 'raw').
        All documents (PDF, DOC, DOCX, TXT) are designated as 'raw' (max 1 MB).
        All images (JPG, PNG, WEBP, GIF, SVG) are designated as 'image' (max 500 KB).
        """
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_ALL_EXTENSIONS:
            raise BadRequestException(
                f"File format '{ext}' is not supported. Allowed formats: {', '.join(sorted(ALLOWED_ALL_EXTENSIONS))}"
            )

        is_image = ext in ALLOWED_IMAGE_EXTENSIONS
        max_size = MAX_IMAGE_SIZE_BYTES if is_image else MAX_DOCUMENT_SIZE_BYTES
        if len(file_bytes) > max_size:
            if is_image:
                uploaded_kb = len(file_bytes) / 1024
                raise BadRequestException(f"Profile picture / image size cannot exceed 500 KB (uploaded file: {uploaded_kb:.1f} KB).")
            else:
                uploaded_mb = len(file_bytes) / (1024 * 1024)
                raise BadRequestException(f"Uploaded document / PDF size cannot exceed 1 MB (uploaded file: {uploaded_mb:.2f} MB).")

        return "image" if is_image else "raw"

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        folder: str = "meditouch/general",
        public_id: Optional[str] = None,
        tags: Optional[list[str]] = None
    ) -> Dict[str, Any]:
        """
        Uploads a file to Cloudinary CDN with automatic folder routing.
        Uses 'raw' resource_type for documents (.pdf, .doc, .docx, .txt) and 'image' for images.
        """
        resource_type = self.validate_file(filename, file_bytes)
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        clean_base = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(filename)[0])[:35]
        uid = uuid.uuid4().hex[:10]

        # For raw files (e.g. .pdf, .doc, .docx), public_id MUST include the extension so downloads and CDN URLs preserve the file type
        if resource_type == "raw":
            custom_public_id = public_id or f"{clean_base}_{uid}.{ext}"
        else:
            custom_public_id = public_id or f"{clean_base}_{uid}"

        if not self.is_configured:
            # Simulated CDN URL when credentials are not configured
            cloud_name = settings.CLOUDINARY_CLOUD_NAME or "meditouch-demo"
            secure_url = f"https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/{folder}/{custom_public_id}"
            if resource_type == "image" and not secure_url.lower().endswith(f".{ext}"):
                secure_url = f"{secure_url}.{ext}"
            return {
                "public_id": f"{folder}/{custom_public_id}",
                "url": secure_url,
                "secure_url": secure_url,
                "format": ext,
                "resource_type": resource_type,
                "bytes": len(file_bytes),
                "original_filename": filename,
                "folder": folder,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }

        try:
            upload_options: Dict[str, Any] = {
                "folder": folder,
                "public_id": custom_public_id,
                "resource_type": resource_type,
                "type": "upload",
                "access_mode": "public",
                "overwrite": True,
                "unique_filename": False,
                "use_filename": False
            }
            if tags:
                upload_options["tags"] = tags

            # Perform upload
            result = cloudinary.uploader.upload(file_bytes, **upload_options)

            res_type = result.get("resource_type", resource_type)
            ret_format = result.get("format") or ext
            secure_url = result.get("secure_url") or result.get("url")

            # For image files, ensure the secure_url has the image extension if not already present
            if res_type == "image" and ret_format and not secure_url.lower().endswith(f".{ret_format.lower()}"):
                secure_url = f"{secure_url}.{ret_format}"
            elif res_type == "raw" and ext and not secure_url.lower().endswith(f".{ext.lower()}"):
                secure_url = f"{secure_url}.{ext}"

            return {
                "public_id": result.get("public_id"),
                "url": secure_url,
                "secure_url": secure_url,
                "format": ret_format,
                "resource_type": res_type,
                "bytes": result.get("bytes", len(file_bytes)),
                "original_filename": filename,
                "folder": folder,
                "created_at": result.get("created_at")
            }
        except Exception as e:
            logger.error(f"Cloudinary upload failed: {e}", exc_info=True)
            raise BadRequestException(f"Cloudinary CDN upload failed: {str(e)}")

    async def delete_file(self, public_id: str, resource_type: str = "image") -> bool:
        if not self.is_configured:
            return True
        try:
            res = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
            return res.get("result") == "ok"
        except Exception as e:
            logger.error(f"Cloudinary delete failed: {e}")
            return False

cloudinary_service = CloudinaryCDNService()
