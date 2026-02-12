from pydantic import BaseModel
from uuid import UUID
from typing import Any

class AuditLogRead(BaseModel):
    id: UUID
    action: str
    meta: dict[str, Any]

    class Config:
        from_attributes = True
