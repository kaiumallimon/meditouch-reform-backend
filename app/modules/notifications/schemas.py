from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from app.common.enums import NotificationType

class NotificationResponse(BaseModel):
    id: str
    user_id: str
    type: NotificationType
    title: str
    message: str
    payload: Optional[Dict[str, Any]] = None
    is_read: bool = False
    created_at: datetime
