from pydantic import BaseModel
from uuid import UUID

class PaymentRead(BaseModel):
    id: UUID
    order_id: UUID
    amount: float

    class Config:
        from_attributes = True
