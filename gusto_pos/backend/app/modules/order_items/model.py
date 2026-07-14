import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, String, Numeric, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class OrderItem(Base):
    __tablename__ = "order_items"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("menu_items.id"), nullable=True)
    name_snap: Mapped[str | None] = mapped_column(String(100))
    price_snap: Mapped[float | None] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Waiter ticks an item off the pending panel once it reaches the table.
    is_served: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    served_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    order = relationship("Order", back_populates="items", lazy="raise")
