import uuid
from sqlalchemy import String, DECIMAL, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Product(Base):
    __tablename__ = "products"
    sku: Mapped[str | None] = mapped_column(String(50), unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    stock_qty: Mapped[float | None] = mapped_column(DECIMAL(10, 2), default=0.00)
    unit: Mapped[str | None] = mapped_column(String(20))

    # Multi-tenancy: products belong to an organization
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    organization = relationship("Organization", back_populates="products", lazy="selectin")
    inventory = relationship("Inventory", back_populates="product", cascade="all, delete-orphan", lazy="selectin")
