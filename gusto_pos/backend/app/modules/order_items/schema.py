from pydantic import BaseModel
from uuid import UUID

class OrderItemRead(BaseModel):
    id: UUID
    order_id: UUID
    product_id: UUID
    quantity: int

    class Config:
        from_attributes = True
