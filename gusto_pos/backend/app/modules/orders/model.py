import uuid
from datetime import datetime
from sqlalchemy import String, DECIMAL, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Order(Base):
    __tablename__ = "orders"

    readable_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"))
    table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tables.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    total_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0.00)

    # Default now 'awaiting_payment'
    order_status: Mapped[str] = mapped_column(String(50), default="awaiting_payment")
    kitchen_token: Mapped[str | None] = mapped_column(String(50))

    # Relationships
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")