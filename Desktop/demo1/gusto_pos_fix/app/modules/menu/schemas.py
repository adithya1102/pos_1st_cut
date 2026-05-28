from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ── Request schemas ───────────────────────────────────────────────────────────

class MenuCreate(BaseModel):
    outlet_id: UUID
    version_label: str | None = None
    is_latest: bool = True


class MenuUpdate(BaseModel):
    version_label: str | None = None
    is_latest: bool | None = None


# ── Nested read schemas ───────────────────────────────────────────────────────
# Only include what the API actually returns — keep it narrow.

class MenuItemRead(BaseModel):
    id: UUID
    name: str
    short_code: str | None
    base_price: float
    is_veg: bool
    is_active: bool

    model_config = {"from_attributes": True}


class CategoryRead(BaseModel):
    id: UUID
    name: str
    menu_items: list[MenuItemRead] = []

    model_config = {"from_attributes": True}


# ── Top-level response schema ─────────────────────────────────────────────────

class MenuRead(BaseModel):
    id: UUID
    outlet_id: UUID
    version_label: str | None
    is_latest: bool
    created_at: datetime
    categories: list[CategoryRead] = []

    model_config = {"from_attributes": True}


class MenuReadSimple(BaseModel):
    """Lightweight response — no nested relationships. Safe to use without eager loads."""
    id: UUID
    outlet_id: UUID
    version_label: str | None
    is_latest: bool
    created_at: datetime

    model_config = {"from_attributes": True}
