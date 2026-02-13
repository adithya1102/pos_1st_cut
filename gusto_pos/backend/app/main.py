from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db, AsyncSessionLocal
from app.core.init_db import init_initial_data

# Import Module Controllers
from app.modules.organizations.controller import router as org_router
from app.modules.outlets.controller import router as outlet_router
from app.modules.users.controller import router as user_router
from app.modules.roles.controller import router as role_router
from app.modules.customers.controller import router as customer_router
from app.modules.menu.controller import router as menu_router
from app.modules.orders.controller import router as order_router
from app.modules.payments.controller import router as payment_router

app = FastAPI(title="Gusto POS", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    await init_db()
    async with AsyncSessionLocal() as session:
        await init_initial_data(session)

# Endpoints
app.include_router(org_router, prefix="/api/v1/organizations", tags=["Organizations"])
app.include_router(outlet_router, prefix="/api/v1/outlets", tags=["Outlets & Tables"])
app.include_router(user_router, prefix="/api/v1/users", tags=["Staff Users"])
app.include_router(role_router, prefix="/api/v1/roles", tags=["Permissions"])
app.include_router(customer_router, prefix="/api/v1/customers", tags=["Customers"])
app.include_router(menu_router, prefix="/api/v1/menu", tags=["Digital Menu"])
app.include_router(order_router, prefix="/api/v1/orders", tags=["Orders"])
app.include_router(payment_router, prefix="/api/v1/payments", tags=["Payments (In-App UPI)"])

@app.get("/")
async def root():
    return {"status": "active", "system": "Gusto POS Backend"}