# app/models/notification.py
# IT35-281 — Notification model (US-014)

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(20), nullable=False)
    # Both required by the OpenAPI contract, so NOT NULL here too (5a1bc9c5c896).
    # Left nullable they let a row exist that NotificationResponse cannot
    # serialize, which surfaced as a 500 on the whole notifications list.
    request_type = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)
    status_change_date = Column(DateTime(timezone=True), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())