import uuid
from sqlalchemy import String, ForeignKey
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

    # Multi-tenancy: customers belong to an organization
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    organization = relationship("Organization", back_populates="customers", lazy="selectin")
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")
