import uuid
from sqlalchemy import String, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Product(Base):
    """Product model - represents inventory items."""
    __tablename__ = "products"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sku: Mapped[str | None] = mapped_column(String(50), unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    stock_qty: Mapped[float | None] = mapped_column(DECIMAL(10, 2), default=0.00)
    unit: Mapped[str | None] = mapped_column(String(20))