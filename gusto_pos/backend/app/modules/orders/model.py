import uuid
from sqlalchemy import ForeignKey, Integer, DECIMAL, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Order(Base):
    __tablename__ = "orders"
    # SERIAL non-PK column — sequence created explicitly by reset_db.py
    readable_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        server_default=text("nextval('orders_readable_id_seq'::regclass)"),
    )
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tables.id"), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    total_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0.00)
    order_status: Mapped[str] = mapped_column(String(20), default="Pending")

    outlet = relationship("Outlet", back_populates="orders", lazy="raise")
    table = relationship("Table", back_populates="orders", lazy="raise")
    customer = relationship("Customer", back_populates="orders", lazy="raise")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="raise")
    payments = relationship("Payment", back_populates="order", cascade="all, delete-orphan", lazy="raise")
