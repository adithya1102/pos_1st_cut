from pydantic import BaseModel
from uuid import UUID
from typing import Optional

class OrderItemRead(BaseModel):
    id: UUID
    order_id: UUID
    menu_item_id: Optional[UUID] = None
    name_snap: Optional[str] = None
    price_snap: Optional[float] = None
    quantity: int
    item_notes: Optional[str] = None

    class Config:
        from_attributes = True
