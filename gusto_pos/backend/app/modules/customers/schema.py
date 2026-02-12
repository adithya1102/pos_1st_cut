"""Pydantic schemas for Customer module."""
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime


class CustomerCreate(BaseModel):
    """Schema for creating a Customer."""
    name: str
    phone_number: str


class CustomerUpdate(BaseModel):
    """Schema for updating a Customer."""
    name: Optional[str] = None
    phone_number: Optional[str] = None


class CustomerResponse(BaseModel):
    """Schema for Customer response."""
    id: UUID
    name: str
    phone_number: str
    created_at: datetime

    class Config:
        from_attributes = True
