from pydantic import BaseModel, computed_field
from uuid import UUID
from typing import Optional


class OrderItemRead(BaseModel):
    id: UUID
    order_id: UUID
    menu_item_id: Optional[UUID] = None
    name_snap: Optional[str] = None
    price_snap: Optional[float] = None
    quantity: int

    @computed_field
    @property
    def name(self) -> str:
        return self.name_snap or ""

    @computed_field
    @property
    def unit_price(self) -> float:
        return self.price_snap or 0.0

    class Config:
        from_attributes = True
