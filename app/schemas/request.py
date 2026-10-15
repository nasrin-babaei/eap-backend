# app/schemas/request.py

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


# US-017 (M4): REQUEST_TYPE_TO_PREFIX used to live here and mapped the seven
# slugs to their prefixes in Python. It is gone. A type created by an admin
# through the UI would never have been in that dict, so POST /requests would
# have rejected it no matter what the database said — which is exactly what
# US-017 ("without code changes") exists to prevent.
# The request_types table is now the only source of truth; every lookup goes
# through its `slug` column.


class RequestCreate(BaseModel):
    request_type: str = Field(
        ...,
        description="Request type slug, e.g. hardware_devices. Must be one of "
                    "the slugs returned by GET /request-types."
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Short title of the request"
    )
    justification: str = Field(
        ...,
        min_length=1,
        description="Business justification"
    )
    

class RequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    request_id: str = Field(
        validation_alias="request_number",
        description="Human-readable ID e.g. HD-001"
    )
    request_type: str
    title: str
    justification: str
    status: str
    approver_id: Optional[int] = None
    message: str = "Request submitted successfully."
    created_at: datetime
    updated_at: datetime


class MyRequestListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    request_id: str = Field(validation_alias="request_number")
    request_type: str
    submission_date: datetime = Field(validation_alias="created_at")
    approver_id: Optional[int] = None
    current_status: str = Field(validation_alias="status")
    updated_at: datetime
    decision_date: Optional[datetime] = None
    rejection_reason: Optional[str] = None


class RequestListResponse(BaseModel):
    items: List[MyRequestListItem]
    total: int
    page: int
    limit: int
    pages: int
    empty_message: Optional[str] = None

class RequestDetailsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    request_id: str = Field(validation_alias="request_number")
    request_type: Optional[str] = Field(
        None,
        validation_alias="request_type_name"
    )
    requester_name: Optional[str] = None
    approver_name: Optional[str] = None
    title: str
    justification: str
    status: str
    submission_date: datetime = Field(validation_alias="created_at")
    updated_at: datetime
    comments: Optional[str] = Field(None, validation_alias="comments_display")
    decision_date: Optional[datetime] = None
    cancellation_date: Optional[datetime] = None

class RequestActionResponse(BaseModel):
    """IT35-264 - returned after completing (and later, cancelling) a request."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    request_id: str
    status: str
    message: str
    completion_date: Optional[datetime] = None
    cancellation_date: Optional[datetime] = None
    updated_at: datetime
