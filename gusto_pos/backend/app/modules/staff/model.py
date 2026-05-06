import enum
from sqlalchemy import String, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class StaffRole(str, enum.Enum):
    Admin = "Admin"
    Waiter = "Waiter"
    Kitchen = "Kitchen"


class Staff(Base):
    __tablename__ = "staff"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[StaffRole] = mapped_column(SAEnum(StaffRole, name="staffrole"), nullable=False)
    hashed_pin: Mapped[str] = mapped_column(String, nullable=False)
    assigned_table: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shift_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    shift_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
