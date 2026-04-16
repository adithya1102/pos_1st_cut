import uuid
from sqlalchemy import ForeignKey, Integer, String, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class OrderItem(Base):
    __tablename__ = "order_items"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("menu_items.id"), nullable=True)
    name_snap: Mapped[str | None] = mapped_column(String(100))
    price_snap: Mapped[float | None] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    order = relationship("Order", back_populates="items", lazy="raise")
