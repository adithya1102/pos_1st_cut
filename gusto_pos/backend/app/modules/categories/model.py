from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Category(Base):
    __tablename__ = "categories"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
