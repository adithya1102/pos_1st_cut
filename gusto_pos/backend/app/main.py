from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.database import init_db, get_db
from app.core.init_db import init_initial_data

# Routers
from app.modules.organizations.controller import router as organizations_router
from app.modules.outlets.controller import router as outlets_router
from app.modules.users.controller import router as users_router
from app.modules.roles.controller import router as roles_router
from app.modules.menu.controller import router as menu_router
from app.modules.categories.controller import router as categories_router
from app.modules.orders.controller import router as orders_router
from app.modules.inventory.controller import router as inventory_router
from app.modules.payments.controller import router as payments_router
from app.modules.sync_logs.controller import router as sync_logs_router
from app.modules.audit_logs.controller import router as audit_logs_router
from app.modules.auth.controller import router as auth_router
from app.modules.customers.controller import router as customers_router

app = FastAPI(title="Gusto POS")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include feature routers under /api/v1
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(outlets_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(roles_router, prefix="/api/v1")
app.include_router(menu_router, prefix="/api/v1")
app.include_router(categories_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(inventory_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(sync_logs_router, prefix="/api/v1")
app.include_router(audit_logs_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(customers_router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup():
    await init_db()
    # Initialize seed data
    async for session in get_db():
        await init_initial_data(session)
        break


@app.get("/")
def read_root():
    return {"message": "Gusto POS System Active", "status": "Online"}

