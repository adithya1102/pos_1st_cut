import uuid
from datetime import date
from sqlalchemy import ForeignKey, DECIMAL, Integer, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class DailySalesSummary(Base):
    __tablename__ = "daily_sales_summary"
    __table_args__ = (
        UniqueConstraint("outlet_id", "sales_date", name="uq_daily_sales_outlet_date"),
    )

    outlet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outlets.id"), nullable=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_revenue: Mapped[float] = mapped_column(DECIMAL(12, 2), default=0.00)
    order_count: Mapped[int] = mapped_column(Integer, default=0)

    outlet = relationship("Outlet", lazy="selectin")
