from uuid import UUID
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
import traceback

from app.modules.outlets.model import Outlet


class OutletService:

    @staticmethod
    async def get_all_outlets(db: AsyncSession):
        stmt = select(Outlet).options(selectinload(Outlet.organization))
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_outlet_by_id(db: AsyncSession, outlet_id: UUID) -> Optional[Outlet]:
        stmt = (
            select(Outlet)
            .options(selectinload(Outlet.organization))
            .where(Outlet.id == outlet_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_outlet(db: AsyncSession, payload: dict[str, Any]):
        try:
            obj = Outlet(**payload)
            db.add(obj)
            await db.commit()
            await db.refresh(obj)  # ensure ID + relationships are available
            return await OutletService.get_outlet_by_id(db, obj.id)

        except IntegrityError:
            await db.rollback()
            print("\n=== INTEGRITY ERROR (CREATE OUTLET) ===")
            traceback.print_exc()
            raise HTTPException(status_code=400, detail="Integrity error")

        except Exception:
            await db.rollback()
            print("\n=== GENERAL ERROR (CREATE OUTLET) ===")
            traceback.print_exc()
            raise

    @staticmethod
    async def update_outlet(db: AsyncSession, outlet_id: UUID, payload: dict[str, Any]):
        try:
            obj = await OutletService.get_outlet_by_id(db, outlet_id)
            if not obj:
                return None

            for k, v in payload.items():
                setattr(obj, k, v)

            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            return await OutletService.get_outlet_by_id(db, outlet_id)

        except IntegrityError:
            await db.rollback()
            print("\n=== INTEGRITY ERROR (UPDATE OUTLET) ===")
            traceback.print_exc()
            raise HTTPException(status_code=400, detail="Integrity error")

        except Exception:
            await db.rollback()
            print("\n=== GENERAL ERROR (UPDATE OUTLET) ===")
            traceback.print_exc()
            raise

    @staticmethod
    async def delete_outlet(db: AsyncSession, outlet_id: UUID) -> bool:
        try:
            obj = await OutletService.get_outlet_by_id(db, outlet_id)
            if not obj:
                return False

            await db.delete(obj)
            await db.commit()
            return True

        except Exception:
            await db.rollback()
            print("\n=== ERROR (DELETE OUTLET) ===")
            traceback.print_exc()
            raise