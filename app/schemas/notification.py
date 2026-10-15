# app/schemas/notification.py
# IT35-282 - GET /notifications response schemas, per OpenAPI spec (IT35-230).

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    user_id: int
    request_id: str
    request_type: str
    status: str
    status_change_date: datetime
    title: str
    message: str
    is_read: bool
    created_at: datetime


class NotificationsResponse(BaseModel):
    items: List[NotificationResponse]
    page: int
    limit: int
    total: int
    unread_count: int
    empty_message: Optional[str] = None