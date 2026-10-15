# app/schemas/request_type.py
# US-017 (IT35-74 / IT35-307 / IT35-308) — request type management.

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestTypeItem(BaseModel):
    """One row of the request_types table, as the API returns it."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: Optional[str] = None
    prefix: str
    is_active: bool
    created_at: datetime


class RequestTypeListResponse(BaseModel):
    items: List[RequestTypeItem]
    total: int
    empty_message: Optional[str] = None


class CreateRequestTypeRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name. Mandatory and unique (compared case-insensitively).",
    )
    description: Optional[str] = Field(default=None, max_length=500)
    prefix: str = Field(
        ...,
        min_length=2,
        max_length=10,
        pattern=r"^[A-Z]+$",
        description="2-10 uppercase letters, unique. Used to build request numbers (HD -> HD-001).",
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_only_whitespace(cls, value: str) -> str:
        """
        min_length=1 alone would accept "   ", which is an empty name as far as
        the user is concerned. Trim first, then reject if nothing is left.
        The trimmed value is what gets stored, so "  Training " and "Training"
        can never both exist.
        """
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Request type name cannot be empty.")
        return trimmed


class UpdateRequestTypeRequest(BaseModel):
    """
    IT35-308 – PATCH /admin/request-types/{id}
    Edits the name and/or description. At least one field must be provided.
    Prefix and slug are immutable (cannot be changed via this endpoint).
    """
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New display name. Must be unique (compared case-insensitively).",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="New description. Can be null to clear it.",
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_only_whitespace(cls, value: Optional[str]) -> Optional[str]:
        """
        If a name is provided, it must not be empty or whitespace-only.
        Trim it before storing.
        """
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("Request type name cannot be empty.")
            return trimmed
        return value

    @model_validator(mode="after")
    def at_least_one_field_provided(self) -> "UpdateRequestTypeRequest":
        """
        At least one of name or description must be present in the request.
        This ensures the PATCH is not a no‑op.
        """
        if self.name is None and self.description is None:
            raise ValueError("At least one of 'name' or 'description' must be provided.")
        return self


class RequestTypeActionResponse(RequestTypeItem):
    """
    A RequestTypeItem plus the confirmation message US-017 asks the UI to show
    after every successful create/update/deactivate/activate.
    """
    message: str