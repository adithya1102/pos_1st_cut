import uuid
import enum
from sqlalchemy import ForeignKey, Integer, DECIMAL, String, Enum as SQLEnum, Sequence
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class OrderStatus(str, enum.Enum):
    """Status enum for orders."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_KITCHEN = "in_kitchen"
    READY = "ready"
    SERVED = "served"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Order(Base):
    """Order model - matches v2.0 schema exactly."""
    __tablename__ = "orders"
    readable_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)  # Serial/Auto-increment
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tables.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    total_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    order_status: Mapped[OrderStatus] = mapped_column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    kitchen_token: Mapped[str | None] = mapped_column(String(50))

    # Relationships
    outlet = relationship("Outlet", back_populates="orders")
    table = relationship("Table", back_populates="orders", foreign_keys=[table_id])
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

