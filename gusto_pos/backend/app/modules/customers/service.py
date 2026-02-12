"""Service layer for Customer operations."""
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.customers.model import Customer
from app.modules.customers.schema import CustomerCreate, CustomerUpdate


class CustomerService:
    """Service for Customer operations."""

    @staticmethod
    async def create_customer(session: AsyncSession, customer: CustomerCreate) -> Customer:
        """Create a new customer."""
        db_customer = Customer(**customer.model_dump())
        session.add(db_customer)
        await session.commit()
        await session.refresh(db_customer)
        return db_customer

    @staticmethod
    async def get_customer_by_id(session: AsyncSession, customer_id: UUID) -> Optional[Customer]:
        """Get a customer by ID."""
        result = await session.execute(select(Customer).filter(Customer.id == customer_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_customer_by_phone(session: AsyncSession, phone_number: str) -> Optional[Customer]:
        """Get a customer by phone number."""
        result = await session.execute(select(Customer).filter(Customer.phone_number == phone_number))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_customers(session: AsyncSession) -> list[Customer]:
        """Get all customers."""
        result = await session.execute(select(Customer))
        return result.scalars().all()

    @staticmethod
    async def update_customer(session: AsyncSession, customer_id: UUID, customer_update: CustomerUpdate) -> Optional[Customer]:
        """Update a customer."""
        db_customer = await CustomerService.get_customer_by_id(session, customer_id)
        if db_customer:
            update_data = customer_update.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_customer, key, value)
            await session.commit()
            await session.refresh(db_customer)
        return db_customer

    @staticmethod
    async def delete_customer(session: AsyncSession, customer_id: UUID) -> bool:
        """Delete a customer."""
        db_customer = await CustomerService.get_customer_by_id(session, customer_id)
        if db_customer:
            await session.delete(db_customer)
            await session.commit()
            return True
        return False
