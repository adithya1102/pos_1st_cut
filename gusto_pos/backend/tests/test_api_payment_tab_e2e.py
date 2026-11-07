"""End-to-end proof for the Payment tab mission (TASK 5).

Walks the FULL chain for one outlet: the owner flips each payment mode on and
off through the real PATCH /pos/outlet/payment-methods route (and the real
admin PATCH for the platform gateway lock), then a customer token calls the
real GET /customer/menu/{outlet_id} and POST /customer/orders routes.

THE ASSERTION THAT MATTERS MOST: at every step, the list the customer
receives from GET /customer/menu equals the owner's own `effective_methods`
from GET /pos/outlet/payment-methods — never a method the owner cannot see on
their own settings screen, and never missing one they can. A disabled mode
must refuse create_order with 409 PAYMENT_METHOD_UNAVAILABLE, and the gateway
must stay out of the customer's list (and refuse PREPAID orders) for as long
as cashfree_unlocked is false, regardless of the owner's own `prepaid` flag.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.modules.carevo_customer.deps import create_customer_token
from app.modules.carevo_customer.service import (
    PAY_AT_PICKUP, PAY_PREPAID, PAY_UPI_MANUAL,
)
from tests.conftest import API

SETTINGS = f"{API}/pos/outlet/payment-methods"
GOOD_VPA = "testrestaurant@okaxis"


def _body(**kw):
    base = {"prepaid": True, "pay_at_pickup": False, "upi_manual": False}
    base.update(kw)
    return base


async def _owner_patch(client, seed, **kw):
    r = await client.patch(SETTINGS, headers=seed["owner_auth"], json=_body(**kw))
    return r


async def _owner_get(client, seed):
    r = await client.get(SETTINGS, headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    return r.json()


async def _customer_menu(client, seed):
    r = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                         headers=seed["customer_auth"])
    assert r.status_code == 200, r.text
    return r.json()["payment_methods"]


async def _create_order(client, seed, method):
    return await client.post(f"{API}/customer/orders",
                             headers=seed["customer_auth"], json={
        "outlet_id": seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
        "payment_method": method,
    })


class TestOwnerToggleMatchesCustomerMenu:
    """Every state the owner can put the outlet into, and what the customer
    sees and can order at each one. The literal matrix is reported in
    PAYMENT_TAB.md; this class is what proves it."""

    async def test_prepaid_only_unlocked(self, client, seed):
        r = await _owner_patch(client, seed,
                                prepaid=True, pay_at_pickup=False, upi_manual=False)
        assert r.status_code == 200, r.text
        owner = await _owner_get(client, seed)
        customer = await _customer_menu(client, seed)

        assert owner["effective_methods"] == [PAY_PREPAID]
        assert customer == [PAY_PREPAID]

        ok = await _create_order(client, seed, PAY_PREPAID)
        assert ok.status_code == 200, ok.text

        refused = await _create_order(client, seed, PAY_AT_PICKUP)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_pay_at_pickup_only(self, client, seed):
        r = await _owner_patch(client, seed,
                                prepaid=False, pay_at_pickup=True, upi_manual=False)
        assert r.status_code == 200, r.text
        owner = await _owner_get(client, seed)
        customer = await _customer_menu(client, seed)

        assert owner["effective_methods"] == [PAY_AT_PICKUP]
        assert customer == [PAY_AT_PICKUP]

        ok = await _create_order(client, seed, PAY_AT_PICKUP)
        assert ok.status_code == 200, ok.text

        refused = await _create_order(client, seed, PAY_PREPAID)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_upi_only(self, client, seed):
        r = await _owner_patch(client, seed,
                                prepaid=False, pay_at_pickup=False, upi_manual=True,
                                upi_vpa=GOOD_VPA, upi_payee_name="Test Kitchen",
                                upi_attested=True)
        assert r.status_code == 200, r.text
        owner = await _owner_get(client, seed)
        customer = await _customer_menu(client, seed)

        assert owner["effective_methods"] == [PAY_UPI_MANUAL]
        assert customer == [PAY_UPI_MANUAL]

        # Checked BEFORE the successful order below: once an order exists,
        # ANY second non-gateway order (pickup OR UPI) is refused by the
        # shared open-order abuse cap regardless of which method is enabled —
        # a different 409 (OPEN_PICKUP_ORDER_PENDING) than the one this
        # assertion is about. Asserting refusal-by-disabled-method needs a
        # customer with no open order yet.
        refused = await _create_order(client, seed, PAY_AT_PICKUP)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

        ok = await _create_order(client, seed, PAY_UPI_MANUAL)
        assert ok.status_code == 200, ok.text

    async def test_all_three_on(self, client, db, seed):
        r = await _owner_patch(client, seed,
                                prepaid=True, pay_at_pickup=True, upi_manual=True,
                                upi_vpa=GOOD_VPA, upi_payee_name="Test Kitchen",
                                upi_attested=True)
        assert r.status_code == 200, r.text
        owner = await _owner_get(client, seed)
        customer = await _customer_menu(client, seed)

        assert set(owner["effective_methods"]) == {
            PAY_PREPAID, PAY_AT_PICKUP, PAY_UPI_MANUAL}
        assert set(customer) == set(owner["effective_methods"])

        # PREPAID (gateway) and PAY_AT_PICKUP (the first non-gateway order)
        # share one customer — the open-order abuse cap only starts counting
        # after the first non-gateway order lands.
        for method in (PAY_PREPAID, PAY_AT_PICKUP):
            ok = await _create_order(client, seed, method)
            assert ok.status_code == 200, f"{method}: {ok.text}"

        # UPI_MANUAL needs its OWN customer: the cap above counts pickup and
        # UPI together (one open unpaid non-gateway order, whichever kind),
        # by deliberate design — see create_order's own re-check. Proving
        # UPI_MANUAL is independently acceptable needs a customer with no
        # open order of either kind.
        upi_cust_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO customers (id, phone_number, name, points_balance,
                                   created_at)
            VALUES (:i, :p, 'UPI Tester', 0, now())"""),
            {"i": str(upi_cust_id), "p": f"+9177{uuid.uuid4().hex[:8]}"})
        await db.commit()
        upi_seed = {**seed, "customer_auth": {
            "Authorization": f"Bearer {create_customer_token(str(upi_cust_id))}"}}
        ok = await _create_order(client, upi_seed, PAY_UPI_MANUAL)
        assert ok.status_code == 200, ok.text

    async def test_turning_one_off_removes_it_from_both_sides(
            self, client, seed):
        """The live-toggle proof: the SAME outlet, before and after one PATCH,
        with the customer's menu re-read in between — exactly the sequence
        checkout's own refetch-on-open is built to catch."""
        await _owner_patch(client, seed,
                           prepaid=True, pay_at_pickup=True, upi_manual=False)
        before_owner = await _owner_get(client, seed)
        before_customer = await _customer_menu(client, seed)
        assert PAY_AT_PICKUP in before_owner["effective_methods"]
        assert PAY_AT_PICKUP in before_customer

        await _owner_patch(client, seed,
                           prepaid=True, pay_at_pickup=False, upi_manual=False)
        after_owner = await _owner_get(client, seed)
        after_customer = await _customer_menu(client, seed)
        assert PAY_AT_PICKUP not in after_owner["effective_methods"]
        assert PAY_AT_PICKUP not in after_customer

        refused = await _create_order(client, seed, PAY_AT_PICKUP)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"


class TestGatewayStaysUnavailableWhileLocked:
    """cashfree_unlocked is platform permission, not the owner's to grant —
    see set_owner_payment_methods's rule 2. This pins that the lock reaches
    the CUSTOMER side too, not just the owner's own settings screen."""

    async def test_locked_gateway_is_absent_from_the_customer_menu(
            self, client, db, seed):
        # Owner wants prepaid AND has pay-at-pickup as a fallback, so the
        # outlet still takes orders once the gateway is withdrawn.
        await _owner_patch(client, seed,
                           prepaid=True, pay_at_pickup=True, upi_manual=False)
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        owner = await _owner_get(client, seed)
        customer = await _customer_menu(client, seed)
        assert owner["cashfree_unlocked"] is False
        assert owner["gateway_available"] is False
        assert owner["gateway_unavailable_reason"] == "CASHFREE_LOCKED"
        assert PAY_PREPAID not in owner["effective_methods"]
        assert PAY_PREPAID not in customer
        assert customer == [PAY_AT_PICKUP]

        refused = await _create_order(client, seed, PAY_PREPAID)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_unlocking_it_again_restores_the_customer_option(
            self, client, db, seed):
        await _owner_patch(client, seed,
                           prepaid=True, pay_at_pickup=True, upi_manual=False)
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        assert PAY_PREPAID not in await _customer_menu(client, seed)

        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": True,
                  "cashfree_unlocked": True})
        assert r.status_code == 200, r.text

        customer = await _customer_menu(client, seed)
        assert PAY_PREPAID in customer

        ok = await _create_order(client, seed, PAY_PREPAID)
        assert ok.status_code == 200, ok.text
