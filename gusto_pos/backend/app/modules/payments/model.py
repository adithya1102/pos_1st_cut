from sqlalchemy import ForeignKey, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Payment(Base):
    __tablename__ = "payments"
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[float] = mapped_column(DECIMAL(10,2))
