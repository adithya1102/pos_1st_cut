from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


class CategoryCreate(BaseModel):
    """Schema for creating a Category."""
    name: str


class CategoryUpdate(BaseModel):
    """Schema for updating a Category."""
    name: Optional[str] = None


class CategoryRead(BaseModel):
    """Schema for Category response."""
    id: UUID
    name: str
    created_at: datetime

    class Config:
        from_attributes = True

