from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db
from app.modules.customers.schema import CustomerCreate, CustomerResponse, CustomerUpdate
from app.modules.customers.service import CustomerService

# FIXED: Removed prefix and tags
router = APIRouter()

@router.post("/", response_model=CustomerResponse)
async def create_customer(customer: CustomerCreate, db: AsyncSession = Depends(get_db)):
    return await CustomerService.create_customer(db, customer)

@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
    customer = await CustomerService.get_customer_by_id(db, customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer

@router.get("/phone/{phone_number}", response_model=CustomerResponse)
async def get_customer_by_phone(phone_number: str, db: AsyncSession = Depends(get_db)):
    customer = await CustomerService.get_customer_by_phone(db, phone_number)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer

@router.get("/", response_model=list[CustomerResponse])
async def get_all_customers(db: AsyncSession = Depends(get_db)):
    return await CustomerService.get_all_customers(db)

@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(customer_id: UUID, customer_update: CustomerUpdate, db: AsyncSession = Depends(get_db)):
    customer = await CustomerService.update_customer(db, customer_id, customer_update)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer

@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await CustomerService.delete_customer(db, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")