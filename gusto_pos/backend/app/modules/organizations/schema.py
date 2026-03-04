from pydantic import BaseModel
from uuid import UUID
from typing import Optional

class OrganizationBase(BaseModel):
    name: str
    gst_number: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    """Schema for updating an Organization."""
    name: Optional[str] = None
    gst_number: Optional[str] = None


class OrganizationRead(OrganizationBase):
    id: UUID

    class Config:
        from_attributes = True
