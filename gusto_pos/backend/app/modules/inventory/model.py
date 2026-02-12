from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Inventory(Base):
    __tablename__ = "inventory"
    product_id: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
