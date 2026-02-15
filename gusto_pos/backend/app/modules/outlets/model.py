import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, Boolean
from app.models.base import Base

class Table(Base):
    __tablename__ = "tables"

    id = Column(Integer, primary_key=True, index=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"))
    table_number = Column(String)  # e.g., "Table 5"
    capacity = Column(Integer)
    is_active = Column(Boolean, default=True)
    
    # ADD THIS: This 8-character code is what goes into the QR URL
    # Example: gusto.app/menu?tid=a1b2c3d4
    qr_code_identifier = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4())[:8])

    def __repr__(self):
        return f"<Table {self.table_number}>"