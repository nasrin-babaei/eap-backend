# app/schemas/approver.py

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ApprovalQueueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    request_id: str = Field(validation_alias="request_number")
    requester_name: str
    request_type: str = Field(validation_alias="request_type_str")
    submission_date: datetime = Field(validation_alias="created_at")
    request_status: str = Field(validation_alias="status")
    updated_at: datetime


class ApprovalQueueStatusCounts(BaseModel):
    """IT35-279 (US-024) — counts across all five tabs, independent of the
    currently selected status/page/limit."""
    pending: int
    approved: int
    rejected: int
    completed: int
    cancelled: int


class ApprovalQueueResponse(BaseModel):
    items: List[ApprovalQueueItem]
    page: int
    limit: int
    total: int
    status_counts: ApprovalQueueStatusCounts
    empty_message: Optional[str] = None


class RejectRequestBody(BaseModel):
    """Body for the reject endpoint — reason is required and cannot be empty."""
    reason: str = Field(..., min_length=1)


class ApproveRequestBody(BaseModel):
    """Body for the approve endpoint — comment is optional."""
    comment: Optional[str] = None
    

class ApprovalDecisionResponse(BaseModel):
    """Returned after approve or reject — includes the updated queue."""
    request_id: str
    status: str
    message: str
    updated_at: datetime
    queue: List[ApprovalQueueItem]