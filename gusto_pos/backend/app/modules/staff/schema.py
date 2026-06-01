import uuid
from typing import Optional
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


class StaffRead(BaseModel):
    id: uuid.UUID
    name: str
    role: StaffRole
    assigned_table: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    earnings_today: float = 0.0

    model_config = {"from_attributes": True}


class StaffCreate(BaseModel):
    name: str
    role: StaffRole
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_4_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 4:
            raise ValueError("PIN must be exactly 4 digits")
        return v


class StaffUpdate(BaseModel):
    assigned_table: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None


class ResetPinRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_4_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 4:
            raise ValueError("PIN must be exactly 4 digits")
        return v
