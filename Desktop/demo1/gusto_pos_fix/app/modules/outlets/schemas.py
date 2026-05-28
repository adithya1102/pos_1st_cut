from datetime import datetime
from uuid import UUID
from decimal import Decimal

from pydantic import BaseModel


class OutletCreate(BaseModel):
    organization_id: UUID
    location_name: str
    city: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    geofence_radius_meters: int = 100


class OutletUpdate(BaseModel):
    location_name: str | None = None
    city: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    geofence_radius_meters: int | None = None


class OutletRead(BaseModel):
    id: UUID
    organization_id: UUID
    location_name: str
    city: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    geofence_radius_meters: int
    created_at: datetime

    # NOTE: No nested orders/menus/users here.
    # Those are fetched via their own endpoints to avoid
    # loading the entire graph on every outlet read.

    model_config = {"from_attributes": True}
