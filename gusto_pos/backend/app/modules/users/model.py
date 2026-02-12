import uuid
from sqlalchemy import String, Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))
    outlet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outlets.id"))

    role = relationship("Role", back_populates="users")
    outlet = relationship("Outlet", back_populates="staff")
