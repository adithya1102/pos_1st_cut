from sqlalchemy import String, DECIMAL, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Product(Base):
    __tablename__ = "products"
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    price: Mapped[float] = mapped_column(DECIMAL(10,2))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))

    category = relationship("Category")
