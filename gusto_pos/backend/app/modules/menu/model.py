import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DECIMAL, Boolean, Integer, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Menu(Base):
    __tablename__ = "menus"
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(50))
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)

    outlet = relationship("Outlet", back_populates="menus", lazy="raise")
    categories = relationship("MenuCategory", back_populates="menu", cascade="all, delete-orphan", lazy="selectin")


class MenuCategory(Base):
    # DDL table name is "categories"
    __tablename__ = "categories"
    menu_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menus.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)

    menu = relationship("Menu", back_populates="categories", lazy="raise")
    items = relationship("MenuItem", back_populates="category", cascade="all, delete-orphan", lazy="selectin")


class MenuItem(Base):
    __tablename__ = "menu_items"
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_code: Mapped[str | None] = mapped_column(String(20))
    base_price: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    is_veg: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Free-form labels ("spicy", "bestseller"), surfaced by /customer/menu.
    #
    # JSON, not JSONB, to match what is already live in prod — see migration
    # 019. Declared here so `Base.metadata.create_all` produces it on a fresh
    # database; without it the menu endpoint 500s on any DB built from this
    # repo alone. The other menu_items columns absent from this model
    # (is_available, prep_time_minutes, image_url, the PE timing fields) are
    # all created by migrations and read via raw SQL, so they are not the same
    # kind of gap — `tags` was created by nothing at all.
    tags: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    category = relationship("MenuCategory", back_populates="items", lazy="raise")
    modifiers = relationship("ItemModifier", back_populates="menu_item", cascade="all, delete-orphan", lazy="selectin")
    history = relationship("MenuHistory", back_populates="menu_item", lazy="selectin")


class ItemModifier(Base):
    __tablename__ = "item_modifiers"
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False)
    modifier_name: Mapped[str] = mapped_column(String(50), nullable=False)
    extra_price: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0.00)

    menu_item = relationship("MenuItem", back_populates="modifiers", lazy="raise")


class MenuHistory(Base):
    __tablename__ = "menu_history"
    # SERIAL primary key — override Base UUID
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("menu_items.id", ondelete="SET NULL"))
    item_name: Mapped[str | None] = mapped_column(String(100))
    old_price: Mapped[float | None] = mapped_column(DECIMAL(10, 2))
    operation_type: Mapped[str | None] = mapped_column(String(20))
    # Renamed from Base created_at to match DDL column name
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    menu_item = relationship("MenuItem", back_populates="history", lazy="selectin")
