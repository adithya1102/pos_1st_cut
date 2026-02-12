from pydantic import BaseModel
from uuid import UUID
from typing import Any

class SyncLogRead(BaseModel):
    id: UUID
    source: str
    payload: dict[str, Any]

    class Config:
        from_attributes = True
