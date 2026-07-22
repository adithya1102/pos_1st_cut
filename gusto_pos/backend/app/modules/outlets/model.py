import uuid
from sqlalchemy import String, ForeignKey, DECIMAL, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Outlet(Base):
    __tablename__ = "outlets"
    location_name: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str | None] = mapped_column(String(50))
    latitude: Mapped[float | None] = mapped_column(DECIMAL(10, 8))
    longitude: Mapped[float | None] = mapped_column(DECIMAL(11, 8))
    geofence_radius_meters: Mapped[int] = mapped_column(Integer, default=100)

    # Platform verification gate (migration 003). Deliberately NO Python-side
    # default: when unset the DB default 'active' applies, so raw-SQL/seed/
    # reset paths keep behaving exactly as before. Only OutletService.create_outlet
    # sets 'pending_verification' explicitly — see the comment there.
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))

    organization = relationship("Organization", back_populates="outlets", lazy="selectin")
    staff = relationship("User", back_populates="outlet", lazy="selectin")
    tables = relationship("Table", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")
    menus = relationship("Menu", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")
    orders = relationship("Order", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")
    inventory = relationship("Inventory", back_populates="outlet", cascade="all, delete-orphan", lazy="selectin")


class Table(Base):
    __tablename__ = "tables"
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    table_number: Mapped[str] = mapped_column(String(10), nullable=False)
    # 0 = Free, 1 = Occupied
    status: Mapped[int] = mapped_column(Integer, default=0)

    outlet = relationship("Outlet", back_populates="tables", lazy="selectin")
