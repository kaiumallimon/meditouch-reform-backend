from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.agent.tools.base import BaseTool
from app.modules.agent.schemas.tools import ToolExecutionStatus, ToolResult
from app.modules.agent.schemas.capabilities import ToolCapability
from app.integrations.cloudinary.client import cloudinary_service
from app.core.config import settings
from app.common.enums import UserRole

class GetCDNStorageStatsTool(BaseTool):
    name = "get_cdn_storage_stats"
    description = "Queries Cloudinary CDN storage volume, byte breakdown by folder, and asset count."
    capability = ToolCapability.READ_CDN_DATA
    roles_allowed = [UserRole.ADMIN.value, UserRole.DEVELOPER.value]
    is_mutation = False
    is_destructive = False
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def execute(self, arguments: Dict[str, Any], caller_id: str, caller_role: str, session_id: str, confirmation_token: Optional[str] = None) -> ToolResult:
        total_assets = await self.db.media_assets.count_documents({})
        total_images = await self.db.media_assets.count_documents({"resource_type": "image"})
        total_docs = await self.db.media_assets.count_documents({"resource_type": {"$ne": "image"}})

        pipeline = [{"$group": {"_id": None, "total_bytes": {"$sum": "$bytes"}}}]
        bytes_res = await self.db.media_assets.aggregate(pipeline).to_list(1)
        total_bytes = bytes_res[0]["total_bytes"] if bytes_res else 0

        # Folder breakdown
        folder_pipeline = [
            {"$group": {"_id": "$folder", "count": {"$sum": 1}, "bytes": {"$sum": "$bytes"}}},
            {"$sort": {"count": -1}},
        ]
        folder_res = await self.db.media_assets.aggregate(folder_pipeline).to_list(10)

        def format_bytes(b: int) -> str:
            if b <= 0:
                return "0 B"
            for u in ["B", "KB", "MB", "GB", "TB"]:
                if b < 1024.0:
                    return f"{b:.1f} {u}"
                b /= 1024.0
            return f"{b:.1f} PB"

        folders = [
            {"folder": f["_id"] or "general", "count": f["count"], "size": format_bytes(f["bytes"])}
            for f in folder_res
        ]

        return ToolResult(
            tool_call_id="",
            name=self.name,
            status=ToolExecutionStatus.SUCCESS,
            result={
                "cloud_name": settings.CLOUDINARY_CLOUD_NAME or "meditouch-cdn",
                "is_configured": cloudinary_service.is_configured,
                "total_assets": total_assets,
                "total_images": total_images,
                "total_documents": total_docs,
                "storage_used": format_bytes(total_bytes),
                "folders": folders,
            },
        )
