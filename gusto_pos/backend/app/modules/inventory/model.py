import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, DECIMAL, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Inventory(Base):
    __tablename__ = "inventory"
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    current_stock: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0.00)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="inventory", lazy="selectin")
    product = relationship("Product", back_populates="inventory", lazy="selectin")
