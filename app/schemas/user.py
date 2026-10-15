# app/schemas/user.py
# US-009 — Admin user & role management

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models.user import UserRole


class UserResponse(BaseModel):
    """The user shape returned by every /admin/users endpoint."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: List[UserResponse]
    page: int
    limit: int
    total: int
    empty_message: Optional[str] = None


class CreateUserRequest(BaseModel):
    # Same reason as UpdateUserRequest below: an unknown field is a caller mistake,
    # so say so instead of ignoring it. Here it also names the offending key, which
    # a plain "name: Field required" does not.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str = Field(..., min_length=1)
    # Minimum length only — the contract does not ask for a stronger policy yet.
    password: str = Field(..., min_length=8)
    role: UserRole


class UpdateUserRequest(BaseModel):
    """
    Edits email and/or name only. Role and active status have their own
    endpoints, so they are deliberately not accepted here.
    Both fields are optional: the admin may send just one of them.

    extra="forbid" makes an unknown field a 422 instead of silently dropping it.
    Without it, a caller sending e.g. {"full_name": "Bob"} gets 200 OK and no
    change at all — a silent failure that looks like success.
    """
    model_config = ConfigDict(extra="forbid")

    email: Optional[EmailStr] = None
    name: Optional[str] = Field(None, min_length=1)


class UpdateRoleRequest(BaseModel):
    role: UserRole