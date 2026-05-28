"""
Gusto POS — FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.modules.menu.router import router as menu_router
from app.modules.outlets.router import router as outlet_router

# Register additional routers as you build them out:
# from app.modules.organizations.router import router as org_router
# from app.modules.orders.router import router as order_router
# from app.modules.categories.router import router as category_router


app = FastAPI(
    title="Gusto POS API",
    version="2.0.0",
    description="Point-of-Sale backend for Gusto restaurants",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(outlet_router, prefix="/api/v1")
app.include_router(menu_router, prefix="/api/v1")

# Uncomment as modules are built:
# app.include_router(org_router, prefix="/api/v1")
# app.include_router(order_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
