from pydantic import BaseModel
from typing import Dict

class RoleBase(BaseModel):
    name: str
    permissions: Dict = {}


class RoleCreate(RoleBase):
    pass


class RoleRead(RoleBase):
    id: int

    class Config:
        from_attributes = True
