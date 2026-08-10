"""Fixtures for the CareVo API suite.

RUNS AGAINST A LOCAL THROWAWAY DATABASE, NEVER PROD.
----------------------------------------------------
DATABASE_URL is overwritten before any app module is imported, so nothing can
bind to the prod engine by accident. There is also a hard assertion below: if
the URL is not the local carevo_test database, collection aborts.

This matters more than usual here. An earlier session established that prod
cannot be cleaned up after an order test: `order_events` has an append-only
trigger (migration 006) that rejects DELETE, and order_events -> customer_orders
-> customers are RESTRICT all the way up. Anything that writes an order to prod
is permanent. A local database is dropped wholesale instead.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

# ---- bind to the test DB BEFORE importing the app ---------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

TEST_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/carevo_test"
os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("SECRET_KEY", "test-secret-not-a-real-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("PAYMENT_GATEWAY", "stub")
os.environ.setdefault("CUSTOMER_AUTH_ENABLED", "true")

assert "127.0.0.1" in TEST_URL and "carevo_test" in TEST_URL, \
    "refusing to run: tests are only ever allowed against the local carevo_test DB"

import logging                                                  # noqa: E402

import pytest                                                   # noqa: E402
import pytest_asyncio                                           # noqa: E402

# The app engine is built with echo=True, which buries test output in SQL.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.CRITICAL)
from httpx import ASGITransport, AsyncClient                    # noqa: E402
from sqlalchemy import text                                     # noqa: E402

from app.core.config import settings                            # noqa: E402
from app.core.database import AsyncSessionLocal                 # noqa: E402
from app.main import app                                        # noqa: E402
from app.core.auth import create_access_token                   # noqa: E402
from app.modules.carevo_customer.deps import create_customer_token  # noqa: E402
from app.core.security import get_password_hash                 # noqa: E402

# Belt and braces: settings must also have resolved to the test DB.
assert "carevo_test" in settings.DATABASE_URL, \
    f"settings bound to the wrong DB: {settings.DATABASE_URL[:60]}"

API = "/api/v1"


@pytest_asyncio.fixture
async def client():
    """In-process HTTP against the real ASGI app — real routing, real
    dependencies, real DB, no network."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def seed(db):
    """A complete, isolated world for one test: org, outlet, menu, staff,
    admin, customer. Every row is unique per test, so tests cannot collide."""
    tag = uuid.uuid4().hex[:8]
    org_id, outlet_id = uuid.uuid4(), uuid.uuid4()
    menu_id, cat_id, item_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owner_id, admin_id, cust_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    await db.execute(text(
        "INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
        {"i": str(org_id), "n": f"Org {tag}"})
    # geofence_radius_meters and verification_status are NOT NULL with no
    # server default, so they must be supplied explicitly — the ORM normally
    # fills them in Python.
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                             upi_id, geofence_radius_meters, verification_status,
                             created_at)
        VALUES (:i,:o,:n,'Testville', true, 'test@upi', 150, 'active', now())"""),
        {"i": str(outlet_id), "o": str(org_id), "n": f"Outlet {tag}"})
    await db.execute(text("""
        INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at)
        VALUES (:i,:o,'v1',true, now())"""), {"i": str(menu_id), "o": str(outlet_id)})
    await db.execute(text("""
        INSERT INTO categories (id, menu_id, name, created_at)
        VALUES (:i,:m,'Mains', now())"""), {"i": str(cat_id), "m": str(menu_id)})
    await db.execute(text("""
        INSERT INTO menu_items (id, category_id, name, base_price, is_veg,
                                is_active, is_available, created_at)
        VALUES (:i,:c,'Test Dish', 100, true, true, true, now())"""),
        {"i": str(item_id), "c": str(cat_id)})

    # A REAL hash: passlib raises UnknownHashError on a malformed one, so a
    # placeholder would make the wrong-password test 500 instead of 401.
    pw_hash = get_password_hash("correct-horse")
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at)
        VALUES (:i,:u,:h, true, :o, now())"""),
        {"i": str(owner_id), "u": f"owner_{tag}", "h": pw_hash, "o": str(outlet_id)})
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, created_at)
        VALUES (:i,:u,:h, true, now())"""),
        {"i": str(admin_id), "u": f"admin_{tag}", "h": pw_hash})

    # roles.id is a serial INTEGER, not a uuid — let the sequence assign it.
    role_id = await db.scalar(text("SELECT id FROM roles WHERE name='SUPER_ADMIN'"))
    if role_id is None:
        role_id = await db.scalar(text(
            "INSERT INTO roles (name, permissions, created_at) "
            "VALUES ('SUPER_ADMIN','{}'::jsonb, now()) RETURNING id"))
    await db.execute(text(
        "INSERT INTO user_roles (user_id, role_id) VALUES (:u,:r) ON CONFLICT DO NOTHING"),
        {"u": str(admin_id), "r": role_id})

    await db.execute(text("""
        INSERT INTO customers (id, phone_number, name, points_balance, created_at)
        VALUES (:i,:p,:n, 0, now())"""),
        {"i": str(cust_id), "p": f"+9199{tag[:8]}", "n": f"Cust {tag}"})
    await db.commit()

    return {
        "tag": tag,
        "outlet_id": str(outlet_id),
        "menu_item_id": str(item_id),
        "owner_id": str(owner_id),
        "owner_username": f"owner_{tag}",
        "admin_username": f"admin_{tag}",
        "customer_id": str(cust_id),
        "customer_auth": {"Authorization": f"Bearer {create_customer_token(str(cust_id))}"},
        "owner_auth": {"Authorization": f"Bearer {create_access_token(subject=f'owner_{tag}')}"},
        "admin_auth": {"Authorization": f"Bearer {create_access_token(subject=f'admin_{tag}')}"},
    }


@pytest_asyncio.fixture
async def paid_order(client, seed):
    """An order already advanced to PAID via the stub simulate endpoint."""
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
        "outlet_id": seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 2}],
    })
    assert r.status_code == 200, r.text
    order = r.json()
    p = await client.post(f"{API}/customer/payment/simulate",
                          headers=seed["customer_auth"],
                          json={"order_id": order["id"], "method": "upi"})
    assert p.status_code == 200, p.text
    return order
