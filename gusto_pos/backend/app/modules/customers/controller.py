# """Controller for Customer module."""
# from uuid import UUID
# from fastapi import APIRouter, Depends, HTTPException, status
# from sqlalchemy.ext.asyncio import AsyncSession
# from app.core.dependencies import get_db
# from app.modules.customers.schema import CustomerCreate, CustomerResponse, CustomerUpdate
# from app.modules.customers.service import CustomerService

# router = APIRouter(prefix="/customers", tags=["customers"])


# @router.post("/", response_model=CustomerResponse)
# async def create_customer(customer: CustomerCreate, db: AsyncSession = Depends(get_db)):
#     """Create a new customer."""
#     return await CustomerService.create_customer(db, customer)


# @router.get("/{customer_id}", response_model=CustomerResponse)
# async def get_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
#     """Get a customer by ID."""
#     customer = await CustomerService.get_customer_by_id(db, customer_id)
#     if not customer:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
#     return customer


# @router.get("/phone/{phone_number}", response_model=CustomerResponse)
# async def get_customer_by_phone(phone_number: str, db: AsyncSession = Depends(get_db)):
#     """Get a customer by phone number."""
#     customer = await CustomerService.get_customer_by_phone(db, phone_number)
#     if not customer:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
#     return customer


# @router.get("/", response_model=list[CustomerResponse])
# async def get_all_customers(db: AsyncSession = Depends(get_db)):
#     """Get all customers."""
#     return await CustomerService.get_all_customers(db)


# @router.put("/{customer_id}", response_model=CustomerResponse)
# async def update_customer(customer_id: UUID, customer_update: CustomerUpdate, db: AsyncSession = Depends(get_db)):
#     """Update a customer."""
#     customer = await CustomerService.update_customer(db, customer_id, customer_update)
#     if not customer:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
#     return customer


# @router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
#     """Delete a customer."""
#     if not await CustomerService.delete_customer(db, customer_id):
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

"""Controller for Customer module."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

# 1. Import get_db directly from database.py to keep it consistent
from app.core.database import get_db

from app.modules.customers.schema import CustomerCreate, CustomerResponse, CustomerUpdate
from app.modules.customers.service import CustomerService
from app.modules.carevo_customer.deps import get_current_staff

# 2. Removed tags=["customers"] to prevent double-prefixing in Swagger UI
#
# STAFF-ONLY, ROUTER-WIDE. Every route here was reachable with no credentials
# at all, including `GET /customers/` (the entire customer table) and
# `GET /customers/phone/{phone_number}` (a PII lookup keyed on exactly the
# identifier a stranger is most likely to have). Nothing in this repository
# calls any of them — the caller audit found the only `customers` references in
# the apps are `/api/v1/admin/customers`, a different and already-authenticated
# router, and a Next.js page path.
#
# Applied on the ROUTER rather than per route, deliberately: a per-route list
# is a list someone can forget to extend, and the next endpoint added to this
# file would be born unauthenticated. The guard is the default here now, and
# opting out has to be a visible, deliberate act.
router = APIRouter(prefix="/customers", dependencies=[Depends(get_current_staff)])


@router.post("/", response_model=CustomerResponse)
async def create_customer(customer: CustomerCreate, db: AsyncSession = Depends(get_db)):
    """Create a new customer."""
    return await CustomerService.create_customer(db, customer)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a customer by ID."""
    customer = await CustomerService.get_customer_by_id(db, customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("/phone/{phone_number}", response_model=CustomerResponse)
async def get_customer_by_phone(phone_number: str, db: AsyncSession = Depends(get_db)):
    """Get a customer by phone number."""
    customer = await CustomerService.get_customer_by_phone(db, phone_number)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("/", response_model=list[CustomerResponse])
async def get_all_customers(db: AsyncSession = Depends(get_db)):
    """Get all customers."""
    return await CustomerService.get_all_customers(db)


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(customer_id: UUID, customer_update: CustomerUpdate, db: AsyncSession = Depends(get_db)):
    """Update a customer."""
    customer = await CustomerService.update_customer(db, customer_id, customer_update)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a customer."""
    if not await CustomerService.delete_customer(db, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")