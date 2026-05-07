import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class TableSession(Base):
    __tablename__ = "table_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token = Column(String(8), unique=True, nullable=False, index=True)
    outlet_id = Column(UUID(as_uuid=True), nullable=False)
    table_id = Column(String(20), nullable=False)   # "T-1", "T-2" etc
    zone = Column(String(20), default="normal")      # "normal" or "fine_dine"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)
