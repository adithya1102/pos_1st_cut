"""Pydantic schemas for User module."""
from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List
from datetime import datetime
from app.modules.roles.schema import RoleRead


class UserBase(BaseModel):
    """Base schema for User."""
    username: str
    outlet_id: Optional[UUID] = None
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for creating a User."""
    password: str
    role_ids: Optional[List[int]] = []


class UserUpdate(BaseModel):
    """Schema for updating a User."""
    username: Optional[str] = None
    outlet_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    role_ids: Optional[List[int]] = None


class UserRead(UserBase):
    """Schema for User response."""
    id: UUID
    created_at: datetime
    roles: List[RoleRead] = []

    class Config:
        from_attributes = True
