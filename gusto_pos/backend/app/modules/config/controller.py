"""Controller for Outlet Configuration (table counts, etc.)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from app.core.database import get_db

router = APIRouter(prefix="/config", tags=["Outlet Config"])


class ConfigUpdate(BaseModel):
    config_key: str
    config_value: str


@router.get("/{outlet_id}")
async def get_outlet_config(outlet_id: str, db: AsyncSession = Depends(get_db)):
    """Get all config values for an outlet."""
    result = await db.execute(
        text("SELECT config_key, config_value FROM outlet_config WHERE outlet_id = :oid"),
        {"oid": outlet_id}
    )
    rows = result.fetchall()
    config = {}
    for row in rows:
        val = row.config_value
        try:
            config[row.config_key] = int(val)
        except ValueError:
            config[row.config_key] = val
    return config


@router.post("/{outlet_id}")
async def update_outlet_config(outlet_id: str, payload: ConfigUpdate, db: AsyncSession = Depends(get_db)):
    """Update a config value for an outlet (upsert)."""
    await db.execute(
        text(
            "INSERT INTO outlet_config (outlet_id, config_key, config_value, updated_at) "
            "VALUES (:oid, :key, :val, NOW()) "
            "ON CONFLICT (outlet_id, config_key) DO UPDATE "
            "SET config_value = :val, updated_at = NOW()"
        ),
        {"oid": outlet_id, "key": payload.config_key, "val": payload.config_value}
    )
    await db.commit()
    return {"status": "updated", "config_key": payload.config_key, "config_value": payload.config_value}
