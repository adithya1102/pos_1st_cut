import uuid, random, string
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, DECIMAL
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class CustomerSession(Base):
    __tablename__ = "customer_sessions"
    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id           = Column(UUID(as_uuid=True), nullable=False)
    table_id            = Column(String(20), nullable=False)
    customer_id         = Column(String(100), nullable=False)
    login_type          = Column(String(20), default="phone")
    customer_name       = Column(String(100), default="")
    is_active           = Column(Boolean, default=True)
    confirmed_by_waiter = Column(Boolean, default=False)
    created_at          = Column(DateTime, default=datetime.utcnow)
    expires_at          = Column(DateTime, nullable=False)

class OtpRecord(Base):
    __tablename__ = "otp_records"
    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone      = Column(String(15), nullable=False)
    otp        = Column(String(6), nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaiterNotification(Base):
    __tablename__ = "waiter_notifications"
    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id     = Column(UUID(as_uuid=True), nullable=False)
    table_id      = Column(String(20), nullable=False)
    customer_name = Column(String(100), default="")
    customer_id   = Column(String(100), default="")
    order_preview = Column(Text, default="")
    notif_type    = Column(String(30), default="confirm_session")
    is_read       = Column(Boolean, default=False)
    is_confirmed  = Column(Boolean, nullable=True)
    session_id    = Column(UUID(as_uuid=True), nullable=True)
    order_id      = Column(UUID(as_uuid=True), nullable=True)
    total_amount  = Column(DECIMAL(10, 2), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
