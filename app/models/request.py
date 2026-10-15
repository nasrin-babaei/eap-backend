# app/models/request.py
import enum
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum as SAEnum, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class RequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"
    cancelled = "cancelled"


class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_number = Column(String(20), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    request_type_id = Column(Integer, ForeignKey("request_types.id"), nullable=False)
    title = Column(String(255), nullable=False)
    justification = Column(Text, nullable=False)
    status = Column(SAEnum(RequestStatus), default=RequestStatus.pending, nullable=False, index=True)
    decision_date = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    approval_comment = Column(Text, nullable=True)
    completion_date = Column(DateTime(timezone=True), nullable=True)
    cancellation_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", foreign_keys=[user_id], back_populates="requests")
    approver = relationship("User", foreign_keys=[approver_id])
    request_type = relationship("RequestType", back_populates="requests")
    comments = relationship("Comment", back_populates="request", order_by="Comment.created_at")