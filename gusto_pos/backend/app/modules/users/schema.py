"""Pydantic schemas for User module."""
from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """Base schema for User."""
    username: str
    role_id: Optional[int] = None
    outlet_id: Optional[UUID] = None
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for creating a User."""
    password: str


class UserUpdate(BaseModel):
    """Schema for updating a User."""
    username: Optional[str] = None
    role_id: Optional[int] = None
    outlet_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class UserRead(UserBase):
    """Schema for User response."""
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

