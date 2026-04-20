import uuid
from pydantic import BaseModel, field_validator
from app.modules.staff.model import StaffRole


class PinLoginRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) < 1:
            raise ValueError("PIN must contain only digits")
        return v


class StaffProfile(BaseModel):
    id: uuid.UUID
    name: str
    role: StaffRole

    model_config = {"from_attributes": True}


class PinLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff: StaffProfile
