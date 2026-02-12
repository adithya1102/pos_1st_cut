from fastapi import Depends
from app.core.database import get_db

def get_db_dep():
    return Depends(get_db)
