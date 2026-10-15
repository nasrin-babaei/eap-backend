from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class AuditLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    request_id: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    timestamp: datetime


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int
    page: int
    limit: int
    empty_message: Optional[str] = None