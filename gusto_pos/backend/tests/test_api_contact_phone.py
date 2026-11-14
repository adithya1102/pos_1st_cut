"""TASK 3 — pay-at-pickup / direct-UPI ask for a phone instead of vanishing.

A phone-less (Google-only) account used to have both non-gateway methods
silently withheld. Now the methods stay offered — flagged requires_phone in
the menu's `payment_methods_detail` — and POST /orders accepts an optional
`contact_phone`: refused 422 PHONE_REQUIRED when neither the request nor the
account has a number, 409 PHONE_IN_USE when the number is another account's,
adopted onto the phone-less account otherwise. An account that already has a
phone and sends nothing behaves exactly as before (rule 8).
"""

import uuid

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.service import (
    PAY_AT_PICKUP, PAY_PREPAID, PAY_UPI_MANUAL, CarevoService,
)
from tests.conftest import API


async def _enable_pickup(db, outlet_id):
    await db.execute(text("""
        UPDATE outlets SET payment_prepaid_enabled = true,
                           payment_pay_at_pickup_enabled = true
        WHERE id = :oid"""), {"oid": outlet_id})
    await db.commit()


@pytest.fixture
async def phoneless(db):
    """A Google-only account: no phone (nullable since migration 008)."""
    from app.modules.carevo_customer.deps import create_customer_token
    cid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customers (id, name, google_uid, points_balance, created_at)
        VALUES (:i, 'Googler', :g, 0, now())"""),
        {"i": str(cid), "g": f"guid-{uuid.uuid4().hex[:12]}"})
    await db.commit()
    return {"customer_id": str(cid),
            "customer_auth": {"Authorization":
                              f"Bearer {create_customer_token(str(cid))}"}}


def _order_body(seed, **extra):
    return {
        "outlet_id": seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
        "payment_method": PAY_AT_PICKUP,
        **extra,
    }


def _ten():
    return "9499" + str(uuid.uuid4().int % 1000000).zfill(6)


@pytest.mark.asyncio
class TestMethodsStayOfferedWithoutPhone:
    async def test_resolver_keeps_pickup_for_a_phoneless_account(
            self, db, seed, phoneless):
        await _enable_pickup(db, seed["outlet_id"])
        cust = (await db.execute(text(
            "SELECT * FROM customers WHERE id = :i"),
            {"i": phoneless["customer_id"]})).first()
        methods = await CarevoService.payment_methods_for(
            db, seed["outlet_id"], cust)
        assert methods == [PAY_PREPAID, PAY_AT_PICKUP]

    async def test_menu_detail_flags_requires_phone(
            self, client, db, seed, phoneless):
        await _enable_pickup(db, seed["outlet_id"])
        r = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                             headers=phoneless["customer_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_methods"] == [PAY_PREPAID, PAY_AT_PICKUP]
        detail = {d["method"]: d["requires_phone"]
                  for d in body["payment_methods_detail"]}
        assert detail == {PAY_PREPAID: False, PAY_AT_PICKUP: True}

    async def test_menu_detail_is_false_for_a_phone_account(
            self, client, db, seed):
        await _enable_pickup(db, seed["outlet_id"])
        r = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        detail = {d["method"]: d["requires_phone"]
                  for d in r.json()["payment_methods_detail"]}
        assert detail[PAY_AT_PICKUP] is False


@pytest.mark.asyncio
class TestContactPhoneOnCreate:
    async def test_no_phone_provided_number_creates_and_adopts(
            self, client, db, seed, phoneless):
        await _enable_pickup(db, seed["outlet_id"])
        ten = _ten()
        r = await client.post(f"{API}/customer/orders",
                              headers=phoneless["customer_auth"],
                              json=_order_body(seed,
                                               contact_phone=f"0{ten}"))
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]
        stored = (await db.execute(text(
            "SELECT contact_phone FROM customer_orders WHERE id = :i"),
            {"i": order_id})).scalar()
        assert stored == f"+91{ten}", "order carries the canonical number"
        adopted = (await db.execute(text(
            "SELECT phone_number FROM customers WHERE id = :i"),
            {"i": phoneless["customer_id"]})).scalar()
        assert adopted == f"+91{ten}", "the phone-less account adopts it"

    async def test_no_phone_nothing_sent_is_422_phone_required(
            self, client, db, seed, phoneless):
        await _enable_pickup(db, seed["outlet_id"])
        r = await client.post(f"{API}/customer/orders",
                              headers=phoneless["customer_auth"],
                              json=_order_body(seed))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "PHONE_REQUIRED"

    async def test_invalid_number_is_422(self, client, db, seed, phoneless):
        await _enable_pickup(db, seed["outlet_id"])
        r = await client.post(f"{API}/customer/orders",
                              headers=phoneless["customer_auth"],
                              json=_order_body(seed,
                                               contact_phone="12345"))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "PHONE_REQUIRED"

    async def test_another_accounts_number_is_409_phone_in_use(
            self, client, db, seed, phoneless):
        await _enable_pickup(db, seed["outlet_id"])
        ten = _ten()
        await db.execute(text("""
            INSERT INTO customers (id, phone_number, points_balance, created_at)
            VALUES (:i, :p, 0, now())"""),
            {"i": str(uuid.uuid4()), "p": f"+91{ten}"})
        await db.commit()

        r = await client.post(f"{API}/customer/orders",
                              headers=phoneless["customer_auth"],
                              json=_order_body(seed, contact_phone=ten))
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PHONE_IN_USE"
        still = (await db.execute(text(
            "SELECT phone_number FROM customers WHERE id = :i"),
            {"i": phoneless["customer_id"]})).scalar()
        assert still is None, "no merge, no adoption"

    async def test_account_with_phone_and_nothing_sent_is_unchanged(
            self, client, db, seed):
        await _enable_pickup(db, seed["outlet_id"])
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"],
                              json=_order_body(seed))
        assert r.status_code == 200, r.text
        stored = (await db.execute(text(
            "SELECT contact_phone FROM customer_orders WHERE id = :i"),
            {"i": r.json()["id"]})).scalar()
        account = (await db.execute(text(
            "SELECT phone_number FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})).scalar()
        assert stored == account, "the pre-existing snapshot behaviour"
