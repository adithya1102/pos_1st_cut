import uuid
from sqlalchemy import String, Boolean, ForeignKey, Table as SATable, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

# Junction table for users ↔ roles many-to-many
user_roles_table = SATable(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    outlet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outlets.id", ondelete="SET NULL"))

    outlet = relationship("Outlet", back_populates="staff", lazy="selectin")
    roles = relationship("Role", secondary=user_roles_table, back_populates="users", lazy="selectin")
    audit_logs = relationship("AuditLog", back_populates="user", lazy="selectin")
