import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DECIMAL, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Customer(Base):
    __tablename__ = "customers"
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Nullable since migration 008: a Google Sign-In customer is a standalone
    # identity with no verified phone until they verify one separately. The DB
    # CHECK (customers_identity_present) guarantees phone_number or google_uid
    # is always set, so a row can never be identity-less.
    phone_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_uid: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Loyalty (migration 010). Running balance kept in step with the
    # point_transactions audit trail, which is the source of truth.
    points_balance: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)

    # Premium window granted by a free-trial coupon (migration 010). NULL means
    # never granted; a past timestamp means lapsed. The customer's "plan" is
    # DERIVED from this, never stored, so the two can never disagree.
    #
    # No billing attaches to this: paid plans are a separate workstream and
    # premium does not gate any behaviour yet.
    premium_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Multi-tenancy: customers belong to an organization
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    organization = relationship("Organization", back_populates="customers", lazy="selectin")
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")
