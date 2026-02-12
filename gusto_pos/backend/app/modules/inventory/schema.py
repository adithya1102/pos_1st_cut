from pydantic import BaseModel
from uuid import UUID

class InventoryRead(BaseModel):
    id: UUID
    product_id: int
    quantity: int

    class Config:
        from_attributes = True
