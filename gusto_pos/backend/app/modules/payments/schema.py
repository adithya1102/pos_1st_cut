from pydantic import BaseModel, ConfigDict
from uuid import UUID
from typing import Optional

class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    amount: float
    payment_method: Optional[str] = None
