
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class RequestType(Base):
    __tablename__ = "request_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # US-017 (M5): the value the API speaks, e.g. "hardware_devices".
    # `name` is what the user reads, `slug` is what every request stores.
    slug = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    prefix = Column(String(10), unique=True, nullable=False)
    counter = Column(Integer, default=0, nullable=False)
    # US-017 (M3): was Column(String, default=True) — a text column holding a
    # boolean. Deactivation is the core of US-017 and needs a real boolean.
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    requests = relationship("Request", back_populates="request_type")