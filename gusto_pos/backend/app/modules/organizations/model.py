from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Organization(Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    gst_number: Mapped[str | None] = mapped_column(String(20))

    outlets = relationship("Outlet", back_populates="organization", cascade="all, delete-orphan", lazy="selectin")
    customers = relationship("Customer", back_populates="organization", lazy="selectin")
    products = relationship("Product", back_populates="organization", lazy="selectin")
