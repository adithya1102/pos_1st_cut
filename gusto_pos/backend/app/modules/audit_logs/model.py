from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    action: Mapped[str] = mapped_column(String(100))
    meta: Mapped[dict] = mapped_column(JSON)
