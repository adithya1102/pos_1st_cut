"""Menu, MenuCategory, MenuItem, and ItemModifier models for v2.0 schema."""
import uuid
from sqlalchemy import String, ForeignKey, DECIMAL, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Menu(Base):
    """Menu model - represents a menu version for an outlet."""
    __tablename__ = "menus"
    outlet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    version_label: Mapped[str] = mapped_column(String(50), nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    outlet = relationship("Outlet", back_populates="menus", lazy="raise")
    categories = relationship("MenuCategory", back_populates="menu", cascade="all, delete-orphan", lazy="selectin")


class MenuCategory(Base):
    """MenuCategory model - categories within a menu."""
    __tablename__ = "menu_categories"
    __table_args__ = {'extend_existing': True}
    menu_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menus.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    menu = relationship("Menu", back_populates="categories", lazy="raise")
    items = relationship("MenuItem", back_populates="category", cascade="all, delete-orphan", lazy="selectin")


class MenuItem(Base):
    """MenuItem model - items within a menu category."""
    __tablename__ = "menu_items"
    # FIXED: Aligned with schema.sql DDL - references menu_categories.id
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_categories.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    short_code: Mapped[str | None] = mapped_column(String(20), unique=True)
    base_price: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    is_veg: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    category = relationship("MenuCategory", back_populates="items", lazy="raise")
    modifiers = relationship("ItemModifier", back_populates="menu_item", cascade="all, delete-orphan", lazy="selectin")


class ItemModifier(Base):
    """ItemModifier model - modifiers for menu items (e.g., size, spice level)."""
    __tablename__ = "item_modifiers"
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    modifier_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extra_price: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)

    # Relationships
    menu_item = relationship("MenuItem", back_populates="modifiers", lazy="raise")