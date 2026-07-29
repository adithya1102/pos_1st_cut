from app.modules.sessions.router import router as sessions_router
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
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
from app.modules.auth.controller import router as auth_router

from app.modules.kitchen.router import router as kitchen_router
from app.modules.kitchen.customer_router import router as customer_ws_router
from app.modules.websocket.router import router as ws_router
from app.modules.tables.router import router as tables_router
from app.modules.config.controller import router as config_router
from app.modules.staff.controller import router as staff_router
from app.modules.categories.controller import router as categories_router
# from app.modules.chat.router import router as chat_router  # disabled: faiss not installed
from app.modules.analytics.router import router as analytics_router

# CareVo Skip (additive; customer pre-order / pickup)
from app.modules.carevo_customer.controller import router as carevo_customer_router
from app.modules.carevo_pos.controller import router as carevo_pos_router
from app.modules.onboarding.controller import router as onboarding_router

# CareVo Admin Dashboard (additive; SUPER_ADMIN-gated platform ops)
from app.modules.carevo_admin.controller import router as carevo_admin_router


app = FastAPI(title="Gusto POS", version="2.0.0")

# Serve kitchen display HTML
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
# Note: The specific paths (like /organizations, /outlets) are already defined 
# inside the controllers, so we only need to prefix them with /api/v1 here.
app.include_router(org_router, prefix="/api/v1", tags=["Organizations"])
app.include_router(outlet_router, prefix="/api/v1", tags=["Outlets & Tables"])
app.include_router(user_router, prefix="/api/v1", tags=["Staff Users"])
app.include_router(role_router, prefix="/api/v1", tags=["Permissions"])
app.include_router(customer_router, prefix="/api/v1", tags=["Customers"])
app.include_router(menu_router, prefix="/api/v1", tags=["Digital Menu"])
app.include_router(order_router, prefix="/api/v1", tags=["Orders"])
app.include_router(payment_router, prefix="/api/v1", tags=["Payments (In-App UPI)"])
app.include_router(auth_router, prefix="/api/v1", tags=["Authentication"])
app.include_router(tables_router, prefix="/api/v1", tags=["Table Sessions"])
app.include_router(sessions_router, prefix="/api/v1", tags=["Sessions"])
app.include_router(config_router, prefix="/api/v1", tags=["Outlet Config"])
app.include_router(kitchen_router)
app.include_router(customer_ws_router)
# /ws/pos/{outlet_id}, /ws/waiter/{outlet_id}, /ws/customer/{table_id}
app.include_router(ws_router)
app.include_router(staff_router, prefix="/api/v1", tags=["Staff Management"])
app.include_router(categories_router, prefix="/api/v1", tags=["Category Management"])
# app.include_router(chat_router, prefix="/api/v1")  # disabled: faiss not installed
app.include_router(analytics_router, prefix="/api/v1")

# CareVo Skip routers → /api/v1/customer/... and /api/v1/pos/...
app.include_router(carevo_customer_router, prefix="/api/v1")
app.include_router(carevo_pos_router, prefix="/api/v1")
# Public owner self-signup → /api/v1/register (unauthenticated, rate-limited).
app.include_router(onboarding_router, prefix="/api/v1")
# CareVo Admin router → /api/v1/admin/...  (inert until migration 003 + a
# SUPER_ADMIN role grant exist; every route 403s for ordinary staff.)
app.include_router(carevo_admin_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"status": "active", "system": "Gusto POS Backend"}
