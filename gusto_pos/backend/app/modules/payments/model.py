import uuid
from sqlalchemy import ForeignKey, DECIMAL, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Payment(Base):
    __tablename__ = "payments"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[float] = mapped_column(DECIMAL(10,2))
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
