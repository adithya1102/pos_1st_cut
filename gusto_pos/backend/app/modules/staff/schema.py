import uuid
from typing import Optional
from pydantic import BaseModel, field_validator
from app.modules.staff.model import StaffRole


class PinLoginRequest(BaseModel):
    """`username` is REQUIRED, and that is a deliberate breaking change.

    Before this, the request carried a PIN and nothing else, and pin_login
    loaded EVERY active user and returned the first whose hash matched. Two
    separate failures came out of that:

      * It is an authentication bypass, not merely a weak lookup. A 4-digit PIN
        has 10,000 values; production holds 1,906 users. By the birthday bound
        a collision is overwhelmingly likely, and the caller is logged in as
        whichever row the unordered scan reached first — not as themselves.

      * It does not scale with a real KDF. Once PINs are bcrypt at cost 12
        (~250ms), scanning 1,906 rows is ~8 minutes of CPU per attempt, which
        turns the endpoint into an unauthenticated CPU-exhaustion lever.

    Supplying the identifier makes the lookup a single indexed row and the
    verification a single hash comparison, which is what "log in" has to mean.
    """

    username: str
    pin: str

    @field_validator("username")
    @classmethod
    def username_must_be_present(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("username is required")
        return v

    @field_validator("pin")
    @classmethod
    def pin_must_be_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) < 1:
            raise ValueError("PIN must contain only digits")
        return v


class StaffProfile(BaseModel):
    id: uuid.UUID
    name: str
    role: str

    model_config = {"from_attributes": True}


class PinLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff: StaffProfile


class StaffRead(BaseModel):
    id: uuid.UUID
    name: str
    role: str
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
