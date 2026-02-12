"""Pydantic schemas for Menu module."""
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime


class ItemModifierCreate(BaseModel):
    """Schema for creating an ItemModifier."""
    name: str
    description: Optional[str] = None
    price_adjustment: float = 0.0


class ItemModifierResponse(BaseModel):
    """Schema for ItemModifier response."""
    id: UUID
    menu_item_id: UUID
    name: str
    description: Optional[str]
    price_adjustment: float
    created_at: datetime

    class Config:
        from_attributes = True


class MenuItemCreate(BaseModel):
    """Schema for creating a MenuItem."""
    category_id: UUID
    name: str
    short_code: Optional[str] = None
    base_price: float
    is_veg: bool = False
    is_active: bool = True


class MenuItemUpdate(BaseModel):
    """Schema for updating a MenuItem."""
    name: Optional[str] = None
    short_code: Optional[str] = None
    base_price: Optional[float] = None
    is_veg: Optional[bool] = None
    is_active: Optional[bool] = None


class MenuItemResponse(BaseModel):
    """Schema for MenuItem response."""
    id: UUID
    category_id: UUID
    name: str
    short_code: Optional[str]
    base_price: float
    is_veg: bool
    is_active: bool
    created_at: datetime
    modifiers: list[ItemModifierResponse] = []

    class Config:
        from_attributes = True


class MenuCategoryCreate(BaseModel):
    """Schema for creating a MenuCategory."""
    menu_id: UUID
    name: str


class MenuCategoryUpdate(BaseModel):
    """Schema for updating a MenuCategory."""
    name: Optional[str] = None


class MenuCategoryResponse(BaseModel):
    """Schema for MenuCategory response."""
    id: UUID
    menu_id: UUID
    name: str
    created_at: datetime
    items: list[MenuItemResponse] = []

    class Config:
        from_attributes = True


class MenuCreate(BaseModel):
    """Schema for creating a Menu."""
    outlet_id: UUID
    version_label: str
    is_latest: bool = False


class MenuUpdate(BaseModel):
    """Schema for updating a Menu."""
    version_label: Optional[str] = None
    is_latest: Optional[bool] = None


class MenuResponse(BaseModel):
    """Schema for Menu response."""
    id: UUID
    outlet_id: UUID
    version_label: str
    is_latest: bool
    created_at: datetime
    categories: list[MenuCategoryResponse] = []

    class Config:
        from_attributes = True
