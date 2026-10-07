"""FCM payload shape (Task 4.1) and the self-service test push (Task 4.2).

WHY THE PAYLOAD SHAPE IS WORTH TESTING
--------------------------------------
owner_app's acceptance alert depends on a Dart background handler running, and
per Firebase's documentation a message carrying a `notification` block is
rendered by the Android system tray WITHOUT invoking that handler while the app
is backgrounded or killed. The handler is what raises the insistent local
notification and, on resolution, cancels it — neither of which a
system-rendered message can do.

So "is there a notification block on this kind" is a functional property, not
cosmetics, and it is invisible at runtime until a real device is asleep. These
tests pin it by capturing the payload _transmit builds.

The transport is never actually called: PushService._configured() is false
without PUSH_ENABLED + a service account, so every send is recorded 'skipped'.
These tests therefore drive _transmit directly with a patched HTTP client.
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash
from app.modules.push import service as push_mod
from app.modules.push.service import (
    KIND_NEW_ORDER_PENDING, KIND_ORDER_RESOLVED, KIND_ORDER_STATUS,
    KIND_STAFF_NEW_ORDER, PushService,
)
from tests.conftest import API


class _FakeResponse:
    status_code = 200
    text = "{}"


class _CapturingClient:
    """Stands in for httpx.AsyncClient and records the one POST body."""

    captured: list[dict] = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002
        _CapturingClient.captured.append(json)
        return _FakeResponse()


@pytest.fixture
def capture_push(monkeypatch):
    """Make _transmit reach the wire, and capture what it would have sent."""
    _CapturingClient.captured = []
    monkeypatch.setattr(push_mod.httpx, "AsyncClient", _CapturingClient)
    monkeypatch.setattr(PushService, "_configured", staticmethod(lambda: True))

    async def _token():
        return "fake-oauth-token"

    monkeypatch.setattr(PushService, "_access_token", staticmethod(_token))
    monkeypatch.setattr(push_mod.settings, "FIREBASE_PROJECT_ID", "test-project")
    return _CapturingClient


async def _transmit(kind: str) -> dict:
    ok, detail = await PushService._transmit(
        "fake-device-token", "A title", "A body",
        {"kind": kind, "order_id": str(uuid.uuid4())},
    )
    assert ok, detail
    return _CapturingClient.captured[-1]["message"]


# --------------------------- 4.1 android block --------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [
    KIND_NEW_ORDER_PENDING, KIND_ORDER_RESOLVED, KIND_ORDER_STATUS,
    KIND_STAFF_NEW_ORDER,
])
async def test_every_kind_gets_high_priority_and_a_short_ttl(capture_push, kind):
    """priority=high lifts the message out of Doze; ttl bounds its usefulness.

    Applied to EVERY kind, not just the acceptance ones: a status push that
    arrives an hour late is also worthless, and nothing here is worth
    delivering later.
    """
    msg = await _transmit(kind)
    assert msg["android"] == {"priority": "high", "ttl": "60s"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [KIND_NEW_ORDER_PENDING, KIND_ORDER_RESOLVED])
async def test_acceptance_kinds_are_data_only(capture_push, kind):
    """NO notification block — otherwise the Dart background handler never runs.

    This is the assertion that protects owner_app's whole alert mechanism.
    """
    msg = await _transmit(kind)
    assert "notification" not in msg, (
        f"{kind} carries a notification block, so Android renders it itself and "
        f"the Dart background handler is never invoked — the insistent alert "
        f"and its cancellation both stop working"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [KIND_NEW_ORDER_PENDING, KIND_ORDER_RESOLVED])
async def test_data_only_kinds_still_carry_the_copy(capture_push, kind):
    """The client builds the notification itself, so it needs title/body."""
    msg = await _transmit(kind)
    assert msg["data"]["title"] == "A title"
    assert msg["data"]["body"] == "A body"
    assert msg["data"]["kind"] == kind


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [KIND_ORDER_STATUS, KIND_STAFF_NEW_ORDER])
async def test_other_kinds_keep_their_notification_block(capture_push, kind):
    """Customer-facing pushes must still render with zero client work."""
    msg = await _transmit(kind)
    assert msg["notification"] == {"title": "A title", "body": "A body"}


@pytest.mark.asyncio
async def test_all_data_values_are_strings(capture_push):
    """FCM v1 rejects non-string data values outright."""
    await PushService._transmit(
        "t", "ti", "bo", {"kind": KIND_ORDER_STATUS, "n": 5, "flag": True},
    )
    data = _CapturingClient.captured[-1]["message"]["data"]
    assert all(isinstance(v, str) for v in data.values()), data
    # And the whole payload must be JSON-serialisable.
    json.dumps(_CapturingClient.captured[-1])


# ------------------------------ 4.2 test push ---------------------------------

@pytest.mark.asyncio
class TestTestPushEndpoint:
    async def test_requires_staff_auth(self, client):
        r = await client.post(f"{API}/pos/devices/test-push")
        assert r.status_code == 401, r.text

    async def test_reports_skipped_when_the_device_has_no_token(
            self, client, seed):
        """The useful failure. The seeded owner has no fcm_token."""
        r = await client.post(f"{API}/pos/devices/test-push",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "skipped"
        assert "fcm_token" in (body["detail"] or ""), body

    async def test_reports_skipped_when_push_is_disabled(self, client, db):
        """A registered token but PUSH_ENABLED false — an operator problem."""
        uname = f"TEST_CAREVO_push_{uuid.uuid4().hex[:8]}"
        outlet = await db.scalar(text("SELECT id FROM outlets LIMIT 1"))
        await db.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active,
                               outlet_id, fcm_token, created_at)
            VALUES (:i,:u,:h,true,:o,'fake-token-aaaaaaaaaaaaaaaa',now())
        """), {"i": str(uuid.uuid4()), "u": uname,
               "h": get_password_hash("x"), "o": str(outlet)})
        await db.commit()

        hdr = {"Authorization": f"Bearer {create_access_token(subject=uname)}"}
        r = await client.post(f"{API}/pos/devices/test-push", headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "skipped"
        assert "push disabled" in (r.json()["detail"] or "").lower()

    async def test_is_rate_limited_to_three_per_minute(self, client, seed):
        from app.modules.carevo_customer.service import _test_push_hits
        _test_push_hits.clear()
        try:
            for i in range(3):
                r = await client.post(f"{API}/pos/devices/test-push",
                                      headers=seed["owner_auth"])
                assert r.status_code == 200, f"attempt {i}: {r.text}"
            blocked = await client.post(f"{API}/pos/devices/test-push",
                                        headers=seed["owner_auth"])
            assert blocked.status_code == 429, blocked.text
            assert blocked.headers.get("Retry-After")
            assert blocked.json()["detail"]["error"] == "too_many_test_pushes"
        finally:
            _test_push_hits.clear()

    async def test_the_limit_is_per_user(self, client, seed, db):
        """One staff member exhausting their budget must not block a colleague."""
        from app.modules.carevo_customer.service import _test_push_hits
        _test_push_hits.clear()
        try:
            for _ in range(3):
                await client.post(f"{API}/pos/devices/test-push",
                                  headers=seed["owner_auth"])
            assert (await client.post(f"{API}/pos/devices/test-push",
                                      headers=seed["owner_auth"])
                    ).status_code == 429

            # A different staff account at the same outlet.
            uname = f"TEST_CAREVO_push2_{uuid.uuid4().hex[:8]}"
            await db.execute(text("""
                INSERT INTO users (id, username, hashed_password, is_active,
                                   outlet_id, created_at)
                VALUES (:i,:u,:h,true,:o,now())
            """), {"i": str(uuid.uuid4()), "u": uname,
                   "h": get_password_hash("x"), "o": seed["outlet_id"]})
            await db.commit()
            hdr = {"Authorization": f"Bearer {create_access_token(subject=uname)}"}
            r = await client.post(f"{API}/pos/devices/test-push", headers=hdr)
            assert r.status_code == 200, (
                f"a colleague was caught by someone else's budget: {r.text}")
        finally:
            _test_push_hits.clear()
