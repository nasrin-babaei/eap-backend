# app/schemas/comment.py

from datetime import datetime
from typing import List
from pydantic import BaseModel, Field, ConfigDict
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommentCreate(BaseModel):
    comment: str = Field(..., min_length=1)

    @field_validator("comment")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Comment content cannot be empty.")
        return value.strip()


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    request_id: str=Field(validation_alias="request_id")
    author_id: int
    author_name: str
    comment: str = Field(validation_alias="content")
    created_at: datetime


class CommentListResponse(BaseModel):
    items: List[CommentResponse]