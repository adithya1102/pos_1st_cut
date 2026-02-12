from pydantic import BaseModel
from uuid import UUID
from typing import Optional

class OrganizationBase(BaseModel):
    name: str
    gst_number: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationRead(OrganizationBase):
    id: UUID

    class Config:
        from_attributes = True
