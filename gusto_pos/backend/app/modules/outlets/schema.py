"""Pydantic schemas for Outlet and Table modules."""
from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime
from enum import Enum


class TableStatusEnum(str, Enum):
    """Table status enum."""
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    RESERVED = "reserved"


class TableCreate(BaseModel):
    """Schema for creating a Table."""
    outlet_id: UUID
    table_number: int
    status: TableStatusEnum = TableStatusEnum.AVAILABLE


class TableUpdate(BaseModel):
    """Schema for updating a Table."""
    table_number: Optional[int] = None
    status: Optional[TableStatusEnum] = None


class TableRead(BaseModel):
    """Schema for Table response."""
    id: UUID
    outlet_id: UUID
    table_number: int
    status: TableStatusEnum
    created_at: datetime

    class Config:
        from_attributes = True


class OutletCreate(BaseModel):
    """Schema for creating an Outlet."""
    organization_id: UUID
    location_name: str
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius_meters: int = 100


class OutletUpdate(BaseModel):
    """Schema for updating an Outlet."""
    location_name: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius_meters: Optional[int] = None


class OutletRead(BaseModel):
    """Schema for Outlet response."""
    id: UUID
    organization_id: UUID
    location_name: str
    city: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    geofence_radius_meters: int
    created_at: datetime

    class Config:
        from_attributes = True

