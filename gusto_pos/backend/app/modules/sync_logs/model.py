from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class SyncLog(Base):
    __tablename__ = "sync_logs"
    source: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
