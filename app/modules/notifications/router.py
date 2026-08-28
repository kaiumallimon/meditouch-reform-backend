from fastapi import APIRouter, Depends
from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongodb import get_db
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.modules.notifications.schemas import NotificationResponse
from app.common.responses import APIResponse
from app.core.security import get_current_user_payload

router = APIRouter(prefix="/notifications", tags=["Notifications"])

def get_notification_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> NotificationService:
    repo = NotificationRepository(db)
    return NotificationService(repo)

@router.get("", response_model=APIResponse[List[NotificationResponse]])
async def get_my_notifications(
    payload: dict = Depends(get_current_user_payload),
    service: NotificationService = Depends(get_notification_service)
):
    notifs = await service.get_user_notifications(payload["sub"])
    return APIResponse(success=True, message="Notifications retrieved", data=notifs)

@router.put("/{notification_id}/read", response_model=APIResponse[dict])
async def mark_notification_as_read(
    notification_id: str,
    payload: dict = Depends(get_current_user_payload),
    service: NotificationService = Depends(get_notification_service)
):
    await service.mark_notification_read(notification_id, payload["sub"])
    return APIResponse(success=True, message="Notification marked as read", data={"id": notification_id})

@router.put("/read-all", response_model=APIResponse[dict])
async def mark_all_notifications_as_read(
    payload: dict = Depends(get_current_user_payload),
    service: NotificationService = Depends(get_notification_service)
):
    count = await service.mark_all_read(payload["sub"])
    return APIResponse(success=True, message=f"{count} notifications marked as read", data={"count": count})

