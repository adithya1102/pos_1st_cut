from pydantic import BaseModel
from uuid import UUID
from typing import Optional

class ProductRead(BaseModel):
    id: UUID
    name: str
    price: float
    category_id: Optional[int]

    class Config:
        from_attributes = True
