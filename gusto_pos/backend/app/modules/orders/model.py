from sqlalchemy import Column, String, Integer, ForeignKey, Float, DateTime
from app.models.base import Base
from datetime import datetime

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    outlet_id = Column(Integer, ForeignKey("outlets.id"))
    table_id = Column(Integer, ForeignKey("tables.id"))
    total_amount = Column(Float)
    
    # UPDATE THIS: Default is now 'awaiting_payment'
    # Valid flow: awaiting_payment -> paid -> preparing -> ready -> completed
    status = Column(String, default="awaiting_payment") 
    
    created_at = Column(DateTime, default=datetime.utcnow)