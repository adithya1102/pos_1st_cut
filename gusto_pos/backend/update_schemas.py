"""Update schemas and router for zone support."""
import os

# Update schemas.py
schemas_content = '''from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid

class TableSessionCreate(BaseModel):
    outlet_id: uuid.UUID
    table_id: str
    zone: str = "normal"

class TableSessionResponse(BaseModel):
    id: uuid.UUID
    token: str
    outlet_id: uuid.UUID
    table_id: str
    zone: str = "normal"
    is_active: bool
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True

class TableSessionValidate(BaseModel):
    token: str
    table_id: str
    outlet_id: str
    zone: str = "normal"
    is_valid: bool
    message: str
'''

schemas_path = os.path.join('app', 'modules', 'tables', 'schemas.py')
with open(schemas_path, 'w') as f:
    f.write(schemas_content)
print(f'Updated {schemas_path}')
