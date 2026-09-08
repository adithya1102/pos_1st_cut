"""Pydantic schemas for Outlet and Table modules."""
from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


# Table status uses integers: 0 = Free, 1 = Occupied
TABLE_FREE = 0
TABLE_OCCUPIED = 1


class TableCreate(BaseModel):
    outlet_id: UUID
    table_number: str
    status: int = TABLE_FREE


class TableUpdate(BaseModel):
    table_number: Optional[str] = None
    status: Optional[int] = None


class TableRead(BaseModel):
    id: UUID
    outlet_id: UUID
    table_number: str
    status: int
    created_at: datetime

    class Config:
        from_attributes = True


class OutletCreate(BaseModel):
    organization_id: UUID
    location_name: str
    city: Optional[str] = None
    phone_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius_meters: int = 100


class OutletUpdate(BaseModel):
    location_name: Optional[str] = None
    city: Optional[str] = None
    phone_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius_meters: Optional[int] = None


class OutletRead(BaseModel):
    id: UUID
    organization_id: UUID
    location_name: str
    city: Optional[str]
    phone_number: Optional[str] = None
    latitude: Optional[float]
    longitude: Optional[float]
    geofence_radius_meters: int
    created_at: datetime

    class Config:
        from_attributes = True
