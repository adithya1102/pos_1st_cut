"""Train transport mode (Timing Engine addendum, Item 1).

Covers the predict_travel branch, the notify_kitchen_at calculation, and — the
point of the last block — that non-train orders are completely unaffected.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio


class TestPredictTravelTrain:
    async def test_train_uses_declared_time_plus_last_mile(self, db, seed):
        from app.modules.prediction.service import (
            PredictionService, TRAIN_DECLARED_SIGMA_S, TRAIN_LAST_MILE_DEFAULT_S)
        arrival = datetime.now(timezone.utc) + timedelta(minutes=30)
        mu, sigma, src = await PredictionService.predict_travel(
            db, seed["outlet_id"], None, None, 12.97, 77.59, "train",
            declared_arrival_at=arrival)
        assert src == "customer_declared", "must not claim a timetable source"
        assert sigma == TRAIN_DECLARED_SIGMA_S
        assert abs(mu - (30 * 60 + TRAIN_LAST_MILE_DEFAULT_S)) < 30

    async def test_train_reads_per_outlet_last_mile_from_outlet_config(self, db, seed):
        from app.modules.prediction.service import PredictionService
        await db.execute(text(
            "INSERT INTO outlet_config (id, outlet_id, config_key, config_value,"
            " created_at, updated_at)"
            " VALUES (:i,:o,'train_last_mile_seconds','120', now(), now())"),
            {"i": str(uuid.uuid4()), "o": seed["outlet_id"]})
        await db.commit()
        arrival = datetime.now(timezone.utc) + timedelta(minutes=10)
        mu, _, src = await PredictionService.predict_travel(
            db, seed["outlet_id"], None, None, 12.97, 77.59, "train",
            declared_arrival_at=arrival)
        assert src == "customer_declared"
        assert abs(mu - (10 * 60 + 120)) < 30, "per-outlet override must win"

    async def test_train_without_declared_time_falls_back(self, db, seed):
        """Train selected but nothing stored: fall back rather than invent."""
        from app.modules.prediction.service import PredictionService
        mu, _, src = await PredictionService.predict_travel(
            db, seed["outlet_id"], 12.9, 77.5, 12.97, 77.59, "train",
            declared_arrival_at=None)
        assert src == "haversine_fallback"
        assert mu > 0

    async def test_past_arrival_clamps_to_zero_not_negative(self, db, seed):
        from app.modules.prediction.service import (
            PredictionService, TRAIN_LAST_MILE_DEFAULT_S)
        past = datetime.now(timezone.utc) - timedelta(minutes=20)
        mu, _, _ = await PredictionService.predict_travel(
            db, seed["outlet_id"], None, None, 12.97, 77.59, "train",
            declared_arrival_at=past)
        assert mu == float(TRAIN_LAST_MILE_DEFAULT_S), "never a negative ETA"


class TestKitchenNotify:
    async def _train_order(self, client, seed, minutes_ahead):
        arrival = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "transport_mode": "train",
            "declared_arrival_at": arrival.isoformat()})
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        await client.post(f"{API}/customer/payment/simulate",
                          headers=seed["customer_auth"],
                          json={"order_id": oid, "method": "upi"})
        return oid

    async def test_declared_arrival_persisted(self, client, seed, db):
        oid = await self._train_order(client, seed, 45)
        row = (await db.execute(text(
            "SELECT transport_mode, declared_arrival_at FROM customer_orders WHERE id=:o"),
            {"o": oid})).first()
        assert row[0] == "train" and row[1] is not None

    async def test_not_yet_due_is_not_notified(self, client, seed, db):
        oid = await self._train_order(client, seed, 360)
        from app.modules.carevo_customer.service import CarevoService
        await CarevoService._notify_kitchen_for_due_trains(db, outlet_id=seed["outlet_id"])
        evs = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='KITCHEN_START_NOTIFIED'"), {"o": oid})
        assert evs == 0, "must not fire hours early"

    async def test_due_order_is_notified_exactly_once(self, client, seed, db):
        oid = await self._train_order(client, seed, 45)
        await db.execute(text(
            "UPDATE customer_orders SET declared_arrival_at = now() + interval "
            "'1 minute' WHERE id=:o"), {"o": oid})
        await db.commit()

        from app.modules.carevo_customer.service import CarevoService
        assert await CarevoService._notify_kitchen_for_due_trains(
            db, outlet_id=seed["outlet_id"]) >= 1
        evs = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='KITCHEN_START_NOTIFIED'"), {"o": oid})
        assert evs == 1

        # Idempotent: the append-only event log IS the guard.
        await CarevoService._notify_kitchen_for_due_trains(db, outlet_id=seed["outlet_id"])
        evs2 = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='KITCHEN_START_NOTIFIED'"), {"o": oid})
        assert evs2 == 1, "second sweep must not re-notify"

    async def test_notify_does_not_touch_status_or_prep_started(self, client, seed, db):
        oid = await self._train_order(client, seed, 45)
        before = await db.scalar(text(
            "SELECT status FROM customer_orders WHERE id=:o"), {"o": oid})
        await db.execute(text(
            "UPDATE customer_orders SET declared_arrival_at = now() WHERE id=:o"),
            {"o": oid})
        await db.commit()
        from app.modules.carevo_customer.service import CarevoService
        await CarevoService._notify_kitchen_for_due_trains(db, outlet_id=seed["outlet_id"])
        after = await db.scalar(text(
            "SELECT status FROM customer_orders WHERE id=:o"), {"o": oid})
        assert after == before, "notification must not move the order's status"
        n = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='PREP_STARTED'"), {"o": oid})
        assert n == 1, "PREP_STARTED stays mark_paid's inferred one, undoubled"

    async def test_push_row_uses_the_new_kind(self, client, seed, db):
        """TRAIN_START_DUE must be insertable — push_kind_valid was widened in
        migration 020. Without that the log INSERT fails SILENTLY (best-effort
        try/except) and the idempotency guard then sees nothing."""
        await client.post(f"{API}/pos/push/register", headers=seed["owner_auth"],
                          json={"fcm_token": "train-token-abcdefghij"})
        oid = await self._train_order(client, seed, 45)
        await db.execute(text(
            "UPDATE customer_orders SET declared_arrival_at = now() WHERE id=:o"),
            {"o": oid})
        await db.commit()
        from app.modules.carevo_customer.service import CarevoService
        await CarevoService._notify_kitchen_for_due_trains(db, outlet_id=seed["outlet_id"])
        row = (await db.execute(text(
            "SELECT kind, status FROM push_notifications WHERE order_id=:o "
            "AND kind='TRAIN_START_DUE'"), {"o": oid})).first()
        assert row is not None, "push row must exist; the CHECK must allow the kind"


class TestNonTrainUnaffected:
    """Regression: none of the above may change any other mode."""

    async def test_bike_order_still_uses_haversine(self, db, seed):
        from app.modules.prediction.service import PredictionService
        _, _, src = await PredictionService.predict_travel(
            db, seed["outlet_id"], 12.9, 77.5, 12.97, 77.59, "bike")
        assert src == "haversine_fallback"

    async def test_non_train_orders_never_notified(self, client, seed, db):
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "transport_mode": "bike", "origin_lat": 12.9, "origin_lng": 77.5,
            "origin_source": "gps"})
        oid = r.json()["id"]
        await client.post(f"{API}/customer/payment/simulate", headers=seed["customer_auth"],
                          json={"order_id": oid, "method": "upi"})
        from app.modules.carevo_customer.service import CarevoService
        await CarevoService._notify_kitchen_for_due_trains(db, outlet_id=seed["outlet_id"])
        n = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='KITCHEN_START_NOTIFIED'"), {"o": oid})
        assert n == 0

    async def test_declared_arrival_null_for_non_train(self, client, seed, db):
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "transport_mode": "walk"})
        v = await db.scalar(text(
            "SELECT declared_arrival_at FROM customer_orders WHERE id=:o"),
            {"o": r.json()["id"]})
        assert v is None
