import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Customer(Base):
    __tablename__ = "customers"
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    # Multi-tenancy: customers belong to an organization
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    organization = relationship("Organization", back_populates="customers", lazy="selectin")
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")
