# app/models/audit_log.py
# EAP-IT35 — Audit Log model
# GDPR: NEVER store raw passwords or full JWT tokens here.
# Only user_id (not email), event type, IP, non-PII metadata.

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action        = Column(String(100), nullable=False)  # LOGIN_SUCCESS | LOGIN_FAIL | REQUEST_APPROVED | REQUEST_REJECTED
    resource_type = Column(String(50),  nullable=True)   # "auth" | "request"
    resource_id   = Column(Integer,     nullable=True)   # user.id on login, request.id on approve/reject, user.id on admin actions
    ip_address    = Column(String(45),  nullable=True)   # IPv4 or IPv6
    old_status    = Column(String(50),  nullable=True)
    new_status    = Column(String(50),  nullable=True)
    timestamp     = Column(DateTime,    nullable=False, default=datetime.utcnow, index=True)