"""The testing dashboard's Scheduled-pickups section — engine observability.

`GET /api/v1/testing/scheduled` exists so a held order can be WATCHED: sitting
held with the numbers that justified its release moment on the row, then
flipping to released at exactly that moment. These tests assert the data behind
that, not the markup.

Same throwaway local DB and same X-Testing-Key gate as the rest of the testing
module — no new auth mechanism was introduced for this endpoint.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_customer.service import CarevoService
from app.modules.testing_dashboard.service import TESTING_TZ

API = "/api/v1"
KEY = "test-dash-key"
HDR = {"X-Testing-Key": KEY}


@pytest.fixture(autouse=True)
def _configure_key():
    """The gate reads settings at request time; set a known key for this file
    and restore afterwards so no other test sees it."""
    prev = settings.TESTING_DASHBOARD_KEY
    settings.TESTING_DASHBOARD_KEY = KEY
    yield
    settings.TESTING_DASHBOARD_KEY = prev


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


async def _scheduled_order(client, seed, minutes_ahead: int = 120):
    """A paid order with a pickup slot far enough out to be genuinely held."""
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
              "requested_pickup_at": _iso(datetime.now(timezone.utc)
                                          + timedelta(minutes=minutes_ahead))})
    assert r.status_code == 200, r.text
    order = r.json()
    p = await client.post(f"{API}/customer/payment/simulate",
                          headers=seed["customer_auth"],
                          json={"order_id": order["id"], "method": "upi"})
    assert p.status_code == 200, p.text
    return order


async def _asap_order(client, seed):
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
    assert r.status_code == 200, r.text
    order = r.json()
    p = await client.post(f"{API}/customer/payment/simulate",
                          headers=seed["customer_auth"],
                          json={"order_id": order["id"], "method": "upi"})
    assert p.status_code == 200, p.text
    return order


async def _rows(client, day=None):
    url = f"{API}/testing/scheduled" + (f"?day={day}" if day else "")
    r = await client.get(url, headers=HDR)
    assert r.status_code == 200, r.text
    return r.json()


async def _row(client, order_id):
    return next((o for o in await _rows(client)
                 if o["order_id"] == str(order_id)), None)


async def _make_due(db, order_id):
    """Bring the pickup moment forward instead of waiting two hours.

    Moves requested_pickup_at, NOT release_at — the latter is re-derived from
    the former on every pass, so poking it directly proves nothing.
    """
    await db.execute(text(
        "UPDATE customer_orders SET requested_pickup_at = now() + interval "
        "'10 seconds' WHERE id=:o"), {"o": str(order_id)})
    await db.execute(text(
        "UPDATE auto_advance_schedule SET due_at = now() - interval '1 minute' "
        "WHERE order_id=:o"), {"o": str(order_id)})
    await db.commit()


# ==========================================================================
# the gate — reused, not reinvented
# ==========================================================================
@pytest.mark.asyncio
class TestScheduledEndpointGate:
    async def test_no_header_is_401(self, client):
        assert (await client.get(f"{API}/testing/scheduled")).status_code == 401

    async def test_a_wrong_key_is_401(self, client):
        r = await client.get(f"{API}/testing/scheduled",
                             headers={"X-Testing-Key": "nope"})
        assert r.status_code == 401

    async def test_the_right_key_passes(self, client, seed):
        r = await client.get(f"{API}/testing/scheduled", headers=HDR)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_it_fails_closed_when_the_key_is_unset(self, client):
        settings.TESTING_DASHBOARD_KEY = ""
        r = await client.get(f"{API}/testing/scheduled", headers=HDR)
        assert r.status_code == 401


# ==========================================================================
# a held order, and why it is held
# ==========================================================================
@pytest.mark.asyncio
class TestHeldOrderIsFullyExplained:
    async def test_a_held_order_appears_with_state_held(self, client, seed):
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row is not None, "a held order must be on the scheduled section"
        assert row["state"] == "held"

    async def test_it_carries_both_timestamps(self, client, seed):
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row["requested_pickup_at"] is not None
        assert row["release_at"] is not None
        assert row["requested_pickup_at_ist"] and row["release_at_ist"]

    async def test_the_release_moment_is_justified_by_the_numbers_shown(
            self, client, seed):
        """The row must not merely assert a moment — the arithmetic behind it
        has to be on the row: release_at = requested - (mu + margin)."""
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row["safety_margin_s"] > 0
        assert row["lead_s"] == row["implied_mu_s"] + row["safety_margin_s"]
        req = datetime.fromisoformat(row["requested_pickup_at"])
        rel = datetime.fromisoformat(row["release_at"])
        assert round((req - rel).total_seconds()) == row["lead_s"]

    async def test_the_logged_mu_matches_what_the_engine_used(self, client, seed):
        """mu_ready_s comes from the prediction_log row the derivation wrote;
        implied_mu_s is backed out of the live timestamps. Their agreement is
        what says this section reports the engine rather than re-deriving its
        own answer beside it — and the tolerance is the derivation deadband,
        not a fudge factor."""
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row["mu_ready_s"] is not None
        assert row["mu_source"] == "order_twin"
        assert abs(row["mu_ready_s"] - row["implied_mu_s"]) \
            <= CarevoService.RELEASE_REDERIVE_DEADBAND_S

    async def test_time_remaining_counts_down_and_is_not_yet_due(
            self, client, seed):
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row["seconds_until_release"] > 0
        assert row["is_due"] is False

    async def test_the_held_order_still_shows_its_pickup_code(self, client, seed):
        """The OTP finding, visible on the same surface: the hold is about what
        the RESTAURANT sees, never about what the customer was given."""
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row["pickup_code"], "a held order has its code from payment on"
        assert row["status"] == "PAID"

    async def test_the_engine_records_that_it_re_derived(self, client, seed):
        order = await _scheduled_order(client, seed)
        row = await _row(client, order["id"])
        assert row["decisions"] >= 1
        assert row["last_decision"] == "held"
        assert row["model_version"] == "release_v1"
        assert row["last_decision_at"] is not None

    async def test_an_asap_order_is_not_in_this_section_at_all(self, client, seed):
        """Scoped to scheduled pickups. An ordinary order has no hold to explain
        and would only be noise here."""
        asap = await _asap_order(client, seed)
        rows = await _rows(client)
        assert all(o["order_id"] != str(asap["id"]) for o in rows)


# ==========================================================================
# the flip — held, then released, at the computed moment
# ==========================================================================
@pytest.mark.asyncio
class TestItFlipsToReleased:
    async def test_the_whole_sequence_on_one_row(self, client, seed, db):
        order = await _scheduled_order(client, seed)
        assert (await _row(client, order["id"]))["state"] == "held"

        await _make_due(db, order["id"])
        row = await _row(client, order["id"])
        assert row["state"] == "released"
        assert row["release_at"] is None, "the hold is cleared at release"
        assert row["seconds_until_release"] is None
        assert row["released_at"] is not None
        assert row["status"] == "RECEIVED", "and it has reached the restaurant"

    async def test_the_read_itself_performs_the_release(self, client, seed, db):
        """This endpoint re-derives before it reads, so it is a release trigger
        in its own right — which is what makes the flip happen on screen even
        while the free-tier background poller is asleep."""
        order = await _scheduled_order(client, seed)
        await _make_due(db, order["id"])
        await _rows(client)
        status, release_at = (await db.execute(text(
            "SELECT status, release_at FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).first()
        assert status == "RECEIVED"
        assert release_at is None

    async def test_the_release_is_logged_as_its_own_decision(
            self, client, seed, db):
        order = await _scheduled_order(client, seed)
        before = (await _row(client, order["id"]))["decisions"]
        await _make_due(db, order["id"])
        after = await _row(client, order["id"])
        assert after["decisions"] > before
        assert after["last_decision"] == "released"

    async def test_a_released_order_keeps_the_numbers_that_released_it(
            self, client, seed, db):
        """The justification must survive the flip. A row that loses its mu and
        margin the moment it releases cannot be audited afterwards — which is
        exactly when someone asks whether the moment was right."""
        order = await _scheduled_order(client, seed)
        await _make_due(db, order["id"])
        row = await _row(client, order["id"])
        assert row["mu_ready_s"] is not None
        assert row["safety_margin_s"] > 0
        assert row["requested_pickup_at"] is not None

    async def test_the_order_is_invisible_to_the_owner_until_it_flips(
            self, client, seed, db):
        """The two surfaces, checked against each other in one test: while the
        dashboard says 'held' the owner queue does not contain the order, and
        both change together."""
        order = await _scheduled_order(client, seed)

        async def queue_ids():
            r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
            assert r.status_code == 200, r.text
            return [str(o["order_id"]) for o in r.json()]

        assert (await _row(client, order["id"]))["state"] == "held"
        assert str(order["id"]) not in await queue_ids()

        await _make_due(db, order["id"])
        assert (await _row(client, order["id"]))["state"] == "released"
        assert str(order["id"]) in await queue_ids()


# ==========================================================================
# scope, ordering, and the states that are not held/released
# ==========================================================================
@pytest.mark.asyncio
class TestScopeAndOrdering:
    async def test_held_orders_sort_before_finished_ones(self, client, seed, db):
        """The section is read as a countdown, so the next thing to happen
        belongs on the top row."""
        done = await _scheduled_order(client, seed, minutes_ahead=150)
        await _make_due(db, done["id"])
        await _rows(client)                     # this read performs that release
        still_held = await _scheduled_order(client, seed, minutes_ahead=120)

        ids = [o["order_id"] for o in await _rows(client)]
        assert ids.index(str(still_held["id"])) < ids.index(str(done["id"]))

    async def test_a_live_hold_is_never_hidden_by_the_day_picker(
            self, client, seed):
        """A hold taken at 22:00 for an 01:00 pickup must not vanish off the
        section at midnight — it is the order most worth watching."""
        order = await _scheduled_order(client, seed)
        other = (datetime.now(TESTING_TZ) - timedelta(days=3)).strftime("%Y-%m-%d")
        rows = await _rows(client, day=other)
        assert any(o["order_id"] == str(order["id"]) for o in rows)

    async def test_a_bad_day_is_a_422_not_a_500(self, client, seed):
        r = await client.get(f"{API}/testing/scheduled?day=not-a-date",
                             headers=HDR)
        assert r.status_code == 422

    async def test_an_order_that_left_the_live_set_reads_as_retired(
            self, client, seed, db):
        """Held, then rejected before its release moment. The section must say
        what actually happened rather than falling back to 'not held', which
        would read as though no hold was ever taken."""
        order = await _scheduled_order(client, seed)
        await CarevoService.reject_order(
            db, uuid.UUID(order["id"]), uuid.UUID(seed["outlet_id"]),
            reason="served early")
        row = await _row(client, order["id"])
        assert row["state"] == "retired"
        assert row["release_at"] is None
        # The reasoning is still there — that is the point of keeping the row.
        assert row["decisions"] >= 1

    async def test_a_day_with_nothing_on_it_returns_only_live_holds(
            self, client, seed):
        """The complement of the test above, and the exact price of it: a day
        the outlet did no business on is not necessarily an empty list, because
        a hold that is live RIGHT NOW is deliberately exempt from the day
        filter. What must never appear is a finished order from another day."""
        other = (datetime.now(TESTING_TZ) - timedelta(days=400)).strftime("%Y-%m-%d")
        rows = await _rows(client, day=other)
        assert all(o["state"] == "held" for o in rows), \
            "only a live hold may bypass the day filter"


# ==========================================================================
# the OTHER surface: the admin dashboard's per-order timeline
# ==========================================================================
@pytest.mark.asyncio
class TestReleaseDecisionReachesTheAdminTimeline:
    """`/admin/prediction/orders/{id}/timeline` selects every prediction_log
    row for an order with NO predictor filter, so the `release` predictor has
    appeared there since 031 — but only its predictor name and mu were ever
    rendered. The admin page now reads `output.decision` and
    `output.release_at` out of that payload, so these pin the contract the UI
    depends on. Without them the page would fail silently: a missing key just
    renders nothing.

    A different gate from the rest of this file — staff bearer + SUPER_ADMIN,
    not X-Testing-Key — which is the point: these are two independent surfaces
    onto the same append-only log.
    """

    async def _timeline(self, client, seed, order_id):
        r = await client.get(
            f"{API}/admin/prediction/orders/{order_id}/timeline",
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        return r.json()

    async def test_the_release_row_carries_its_decision_and_moment(
            self, client, seed):
        order = await _scheduled_order(client, seed)
        tl = await self._timeline(client, seed, order["id"])
        rel = [p for p in tl["predictions"] if p["predictor"] == "release"]
        assert rel, "the release predictor must appear on the admin timeline"
        out = rel[-1]["output"]
        assert out["decision"] == "held"
        assert out["release_at"] is not None
        assert rel[-1]["model_version"] == "release_v1"

    async def test_the_released_decision_shows_up_after_the_flip(
            self, client, seed, db):
        order = await _scheduled_order(client, seed)
        await _make_due(db, order["id"])
        await _rows(client)                     # this read performs the release
        tl = await self._timeline(client, seed, order["id"])
        decisions = [p["output"].get("decision")
                     for p in tl["predictions"] if p["predictor"] == "release"]
        assert "held" in decisions and "released" in decisions, \
            "both sides of the flip must be readable after the fact"

    async def test_no_other_predictor_emits_these_keys(self, client, seed):
        """Why the page can read `output.decision` generically instead of
        branching on `predictor === "release"`. If a future predictor starts
        emitting either key this fails, and whoever added it gets to decide
        whether the admin badge should render for it."""
        order = await _scheduled_order(client, seed)
        tl = await self._timeline(client, seed, order["id"])
        others = [p for p in tl["predictions"] if p["predictor"] != "release"]
        assert others, "sanity: the original five predictors still log"
        for p in others:
            out = p["output"] or {}
            assert "decision" not in out, f"{p['predictor']} now emits decision"
            assert "release_at" not in out, f"{p['predictor']} now emits release_at"

    async def test_an_asap_order_has_no_release_row_at_all(self, client, seed):
        """The badge must not appear for an ordinary order — there is no hold
        to describe, so there is no row to render."""
        asap = await _asap_order(client, seed)
        tl = await self._timeline(client, seed, asap["id"])
        assert not [p for p in tl["predictions"] if p["predictor"] == "release"]

    async def test_the_timeline_is_super_admin_gated(self, client, seed):
        order = await _scheduled_order(client, seed)
        anon = await client.get(
            f"{API}/admin/prediction/orders/{order['id']}/timeline")
        assert anon.status_code in (401, 403)
        as_owner = await client.get(
            f"{API}/admin/prediction/orders/{order['id']}/timeline",
            headers=seed["owner_auth"])
        assert as_owner.status_code == 403


# ==========================================================================
# the THIRD surface: admin_app's read-only Scheduled Orders view
# ==========================================================================
@pytest.mark.asyncio
class TestAdminScheduledOrdersView:
    """`/admin/prediction/scheduled` answers the same question as
    `/testing/scheduled`, on admin_app's own SUPER_ADMIN auth rather than the
    X-Testing-Key — no new gate was introduced.

    The load-bearing difference is that this one is READ-ONLY: it does not call
    refresh_scheduled_releases, so opening the admin page cannot hand an order
    to a kitchen as a side effect. That is asserted directly below, because it
    is the property a future "just reuse the testing query" refactor would
    silently destroy.
    """

    async def _admin(self, client, seed, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        r = await client.get(
            f"{API}/admin/prediction/scheduled" + (f"?{q}" if q else ""),
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        return r.json()

    async def test_a_held_order_is_listed_with_what_the_view_shows(
            self, client, seed):
        order = await _scheduled_order(client, seed)
        row = next(o for o in await self._admin(client, seed)
                   if o["order_id"] == str(order["id"]))
        assert row["state"] == "held"
        assert row["outlet_name"], "the restaurant is named"
        assert row["items"], "the items are listed"
        assert row["requested_pickup_at"] is not None
        assert row["release_at"] is not None

    async def test_the_engine_numbers_come_along(self, client, seed):
        order = await _scheduled_order(client, seed)
        row = next(o for o in await self._admin(client, seed)
                   if o["order_id"] == str(order["id"]))
        assert row["mu_ready_s"] is not None
        assert row["safety_margin_s"] > 0
        assert row["lead_s"] == row["mu_ready_s"] + row["safety_margin_s"] \
            or abs(row["lead_s"] - row["mu_ready_s"] - row["safety_margin_s"]) \
            <= CarevoService.RELEASE_REDERIVE_DEADBAND_S
        assert row["decisions"] >= 1

    async def test_reading_it_does_NOT_release_a_due_order(
            self, client, seed, db):
        """The read-only guarantee, stated as the thing that would break it.

        /testing/scheduled deliberately releases on read; this must not. An
        admin opening a page to look at the business must not move orders.
        """
        order = await _scheduled_order(client, seed)
        await _make_due(db, order["id"])

        await self._admin(client, seed)          # the read under test

        status, release_at = (await db.execute(text(
            "SELECT status, release_at FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).first()
        assert status == "PAID", "the admin read must not advance the order"
        assert release_at is not None, "nor clear its hold"

    async def test_an_asap_order_never_appears(self, client, seed):
        asap = await _asap_order(client, seed)
        rows = await self._admin(client, seed)
        assert all(o["order_id"] != str(asap["id"]) for o in rows)

    async def test_held_orders_sort_before_finished_ones(self, client, seed, db):
        done = await _scheduled_order(client, seed, minutes_ahead=150)
        await _make_due(db, done["id"])
        await _rows(client)                      # release it via the testing path
        still_held = await _scheduled_order(client, seed, minutes_ahead=120)
        ids = [o["order_id"] for o in await self._admin(client, seed)]
        assert ids.index(str(still_held["id"])) < ids.index(str(done["id"]))

    async def test_a_released_order_still_shows_its_reasoning(
            self, client, seed, db):
        order = await _scheduled_order(client, seed)
        await _make_due(db, order["id"])
        await _rows(client)                      # release via the testing path
        row = next(o for o in await self._admin(client, seed)
                   if o["order_id"] == str(order["id"]))
        assert row["state"] == "released"
        assert row["released_at"] is not None
        assert row["mu_ready_s"] is not None

    async def test_it_is_super_admin_gated_not_testing_key_gated(
            self, client, seed):
        anon = await client.get(f"{API}/admin/prediction/scheduled")
        assert anon.status_code in (401, 403)
        as_owner = await client.get(f"{API}/admin/prediction/scheduled",
                                    headers=seed["owner_auth"])
        assert as_owner.status_code == 403
        with_testing_key = await client.get(
            f"{API}/admin/prediction/scheduled", headers=HDR)
        assert with_testing_key.status_code in (401, 403), \
            "the testing key must not open an admin route"
