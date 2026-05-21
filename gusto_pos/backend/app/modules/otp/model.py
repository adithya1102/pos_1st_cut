from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class OtpValidation(Base):
    __tablename__ = "otp_validations"
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    otp_code: Mapped[str] = mapped_column(String(10), nullable=False)
    expiry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
