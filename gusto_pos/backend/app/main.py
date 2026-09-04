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

# Local testing dashboard (additive; every route gated by X-Testing-Key)
from app.modules.testing_dashboard.controller import router as testing_router

# CareVo Admin Dashboard (additive; SUPER_ADMIN-gated platform ops)
from app.modules.carevo_admin.controller import router as carevo_admin_router
from app.modules.account.controller import (
    public_router as account_public_router,
    router as account_router,
)
from app.modules.push.controller import (
    admin_router as push_admin_router,
    customer_router as push_customer_router,
)
# Promotions (migration 016): CareVo Campaigns + Restaurant Offers.
from app.modules.promotions.controller import (
    admin_router as promotions_admin_router,
    customer_router as promotions_customer_router,
    pos_router as promotions_pos_router,
)


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


@app.on_event("startup")
async def _start_auto_advance_poller():
    """Durable roster auto-progression: a background loop that advances due
    steps recorded in auto_advance_schedule (migration 028). Persisting the
    schedule is what makes progression survive restarts; this loop is only the
    driver. Lazily imported so importing the app (e.g. in tests) has no side
    effect — and the httpx test client never fires startup, so it stays off in
    the suite, which drives the processor directly instead."""
    import asyncio
    from app.modules.testing_dashboard.service import auto_advance_poller_loop
    app.state.auto_advance_task = asyncio.create_task(auto_advance_poller_loop())


@app.on_event("shutdown")
async def _stop_auto_advance_poller():
    task = getattr(app.state, "auto_advance_task", None)
    if task is not None:
        task.cancel()

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
# Local testing dashboard → /api/v1/testing/... (all routes X-Testing-Key gated)
app.include_router(testing_router, prefix="/api/v1")
# Public owner self-signup → /api/v1/register (unauthenticated, rate-limited).
app.include_router(onboarding_router, prefix="/api/v1")
# CareVo Admin router → /api/v1/admin/...  (inert until migration 003 + a
# SUPER_ADMIN role grant exist; every route 403s for ordinary staff.)
app.include_router(carevo_admin_router, prefix="/api/v1")
# Push notifications (migration 014). Token registration is customer-authed;
# the nudge triggers are SUPER_ADMIN-only. Sending stays inert until
# PUSH_ENABLED + a Firebase service account are configured.
# Owner account: email on file, change password, forgot/reset password
# (migration 015). The /auth/password/* pair is PUBLIC by necessity — a
# locked-out owner has no token. Email sending stays inert until EMAIL_ENABLED.
app.include_router(account_router, prefix="/api/v1")
app.include_router(account_public_router, prefix="/api/v1")
app.include_router(push_customer_router, prefix="/api/v1")
app.include_router(push_admin_router, prefix="/api/v1")
# Promotions (migration 016) → /api/v1/admin/promotions (SUPER_ADMIN),
# /api/v1/pos/offers (outlet staff, own outlet only), /api/v1/customer/offers.
# Two DISTINCT products sharing one table, never one generic coupon: `scope`
# alone decides who funds the discount and is set by the route, not the body.
app.include_router(promotions_admin_router, prefix="/api/v1")
app.include_router(promotions_pos_router, prefix="/api/v1")
app.include_router(promotions_customer_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"status": "active", "system": "Gusto POS Backend"}
