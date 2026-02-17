import uuid
from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Outlet(Base):
    __tablename__ = "outlets"
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    location_name: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str | None] = mapped_column(String(50))
    geofence_radius_meters: Mapped[int | None] = mapped_column(Integer, default=100)

    # Relationships
    tables = relationship("Table", back_populates="outlet", cascade="all, delete-orphan")
    menus = relationship("Menu", back_populates="outlet", cascade="all, delete-orphan")
    staff = relationship("User", back_populates="outlet")
    # Back-reference to Organization
    organization = relationship("Organization", back_populates="outlets")


class Table(Base):
    __tablename__ = "tables"

    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"))
    table_number: Mapped[str] = mapped_column(String(50))  # e.g., "Table 5"
    capacity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[int] = mapped_column(Integer, default=0)  # 0=Free,1=Occupied
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 8-character code used in QR URL (e.g., ?tid=a1b2c3d4)
    qr_code_identifier: Mapped[str] = mapped_column(String(8), unique=True, index=True, default=lambda: str(uuid.uuid4())[:8])

    outlet = relationship("Outlet", back_populates="tables")

    def __repr__(self):
        return f"<Table {self.table_number}>"