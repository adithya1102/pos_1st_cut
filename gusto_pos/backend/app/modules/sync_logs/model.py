import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class SyncLog(Base):
    __tablename__ = "sync_logs"
    outlet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outlets.id"), nullable=True)
    sync_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    outlet = relationship("Outlet", lazy="selectin")
