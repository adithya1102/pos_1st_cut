import uuid
from sqlalchemy import String, ForeignKey, DECIMAL, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import enum


class TableStatus(str, enum.Enum):
    """Status enum for tables."""
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    RESERVED = "reserved"


class Outlet(Base):
    __tablename__ = "outlets"
    location_name: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str | None] = mapped_column(String(50))
    latitude: Mapped[float | None] = mapped_column(DECIMAL(10, 8))
    longitude: Mapped[float | None] = mapped_column(DECIMAL(11, 8))
    geofence_radius_meters: Mapped[int] = mapped_column(Integer, default=100)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))

    # Relationships
    organization = relationship("Organization", back_populates="outlets", lazy="selectin")
    staff = relationship("User", back_populates="outlet", lazy="selectin")
    tables = relationship("Table", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")
    menus = relationship("Menu", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")
    orders = relationship("Order", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")


class Table(Base):
    """Table model - represents physical tables in an outlet."""
    __tablename__ = "tables"
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    table_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TableStatus] = mapped_column(SQLEnum(TableStatus), default=TableStatus.AVAILABLE)

    # Relationships
    outlet = relationship("Outlet", back_populates="tables", lazy="selectin")
    orders = relationship("Order", back_populates="table", foreign_keys="Order.table_id", lazy="selectin")
