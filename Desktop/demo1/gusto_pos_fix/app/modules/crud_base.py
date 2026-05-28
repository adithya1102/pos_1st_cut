"""
Generic async CRUD base.

Key rules:
  - NEVER call db.refresh() without explicit attribute_names.
  - NEVER rely on lazy loading — always pass selectinload options into every query.
  - expire_on_commit=False is set on the session factory, so post-commit
    access is safe IF the attributes were loaded before commit.
"""

from typing import Any, Generic, Sequence, Type, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class CRUDBase(Generic[ModelType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(
        self,
        db: AsyncSession,
        id: UUID,
        *load_options,          # pass selectinload(...) chains here
    ) -> ModelType | None:
        stmt = select(self.model).where(self.model.id == id)
        for opt in load_options:
            stmt = stmt.options(opt)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        *load_options,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[ModelType]:
        stmt = select(self.model).offset(skip).limit(limit)
        for opt in load_options:
            stmt = stmt.options(opt)
        result = await db.execute(stmt)
        return result.scalars().all()

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        obj_in: dict[str, Any],
        *load_options,          # relationships to load after creation
    ) -> ModelType:
        obj = self.model(**obj_in)
        db.add(obj)
        await db.commit()
        # Refresh only scalar columns — never trigger relationship loads
        await db.refresh(obj)
        # Now eagerly load requested relationships
        if load_options:
            stmt = select(self.model).where(self.model.id == obj.id)
            for opt in load_options:
                stmt = stmt.options(opt)
            result = await db.execute(stmt)
            obj = result.scalar_one()
        return obj

    async def update(
        self,
        db: AsyncSession,
        obj: ModelType,
        update_data: dict[str, Any],
        *load_options,
    ) -> ModelType:
        for field, value in update_data.items():
            setattr(obj, field, value)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        if load_options:
            stmt = select(self.model).where(self.model.id == obj.id)
            for opt in load_options:
                stmt = stmt.options(opt)
            result = await db.execute(stmt)
            obj = result.scalar_one()
        return obj

    async def delete(self, db: AsyncSession, id: UUID) -> bool:
        obj = await self.get(db, id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True
