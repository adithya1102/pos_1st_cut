"""
CareVo Skip ORM models. These map to already-existing tables (migration applied
out of band). Relationships are kept SELF-CONTAINED among these three models —
no back_populates is attached to existing Customer/Outlet/MenuItem mappers, so
existing mappings are untouched.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, DECIMAL, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CustomerOrder(Base):
    __tablename__ = "customer_orders"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    outlet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outlets.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="CREATED")
    total_amount: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    payment_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    pickup_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    pickup_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    customer_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Base already defines created_at; override to timestamptz to match DDL.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    items = relationship(
        "CustomerOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    transactions = relationship(
        "PaymentTransaction",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CustomerOrderItem(Base):
    __tablename__ = "customer_order_items"

    customer_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=True
    )
    name_snap: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price_snap: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    customizations: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    item_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    order = relationship("CustomerOrder", back_populates="items", lazy="raise")


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    customer_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    gateway: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gateway_order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    gateway_payment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    gateway_signature: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="CREATED")
    raw_payload: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    order = relationship("CustomerOrder", back_populates="transactions", lazy="raise")
