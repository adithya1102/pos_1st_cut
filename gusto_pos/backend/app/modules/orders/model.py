import uuid
import enum
from sqlalchemy import ForeignKey, Integer, DECIMAL, String, Enum as SQLEnum, Sequence, text
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
    PAID = "paid"


class Order(Base):
    """Order model - matches v2.0 schema exactly."""
    __tablename__ = "orders"
    readable_id: Mapped[int] = mapped_column(
        Integer, unique=True,
        server_default=text("nextval('orders_readable_id_seq'::regclass)"),
    )
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    table_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    total_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    order_status: Mapped[str] = mapped_column(String(20), default="pending")
    kitchen_token: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(20), default="customer")

    # Relationships — lazy="raise" to prevent cascade loads in async
    outlet = relationship("Outlet", back_populates="orders", lazy="raise")
    customer = relationship("Customer", back_populates="orders", lazy="raise")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="raise")

