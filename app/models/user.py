
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Enum, DateTime, Boolean
from app.database import Base
from sqlalchemy.orm import relationship
class UserRole(enum.Enum):
    requester = "requester"
    approver = "approver"
    admin = "admin"

# GDPR: PII alanları burada
class User(Base):
    __tablename__ = "users"

    # PII alanları
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False, default="")
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.requester)
    is_active = Column(Boolean, default=True)

    # Audit alanları (GDPR: PII'dan ayrı)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    requests = relationship(
        "Request",
        back_populates="user",
        foreign_keys="Request.user_id"
    )
