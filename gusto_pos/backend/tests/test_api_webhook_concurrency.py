"""Task 3c — two identical webhooks, truly concurrent, over a REAL socket.

Everything else in this suite runs through httpx's ASGITransport, which calls
straight into the app with no network stack and, crucially, no real
concurrency: two "concurrent" ASGITransport calls still interleave inside
ONE event loop cooperatively, never racing at the TCP/driver level. This file
starts a real uvicorn server on a real local TCP socket, against the same
local carevo_test database every other test uses, and fires two byte-identical
PAYMENT_SUCCESS_WEBHOOK requests at it with asyncio.gather — genuine
concurrency, over the wire.

LITERAL BEHAVIOUR BEFORE THE Task 3c FIX: mark_paid (carevo_customer/
service.py) took no lock on the order row. Two near-simultaneous webhook
deliveries for the same order (Cashfree's own retry landing mid-flight, or a
true race) could both read payment_status != 'PAID' before either had
committed, and both fall through into the PAID-transition body: double
loyalty-point accrual (point_transactions.(order_id, reason='ORDER_ACCRUAL')
has a partial unique index per migration 010, so the SECOND insert would
raise an IntegrityError — an unhandled exception inside a request path,
i.e. a 500 for the loser) and two pickup codes minted.

FIXED: mark_paid now takes `SELECT ... FOR UPDATE` on the order row before
either idempotency check, serializing concurrent calls. The second caller
blocks until the first COMMITs, re-reads the now-PAID row, and takes the
ordinary idempotent short-circuit — answering 200 with an unchanged, already-
PAID order. No 500, ever.

Verification goes over the SAME real HTTP server (GET /customer/orders/{id}
and GET /customer/points), not a second direct DB connection — asyncpg
connections are bound to the event loop that created them, and mixing the
uvicorn thread's loop with pytest-asyncio's loop on the same SQLAlchemy engine
is exactly the kind of cross-loop corruption this file must not itself
introduce.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.core.config import settings
from app.main import app
from tests.conftest import API

CF_SECRET = "whsec_concurrency_test_only"
TRIALS = 20


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _RealServer:
    """A real uvicorn server for the app, on a real socket, lifespan off
    (on_startup is exercised elsewhere; here it would re-run init_initial_data
    against a DB the suite has already seeded, and is not what this file is
    testing)."""

    def __init__(self):
        self.port = _free_port()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port,
            log_level="warning", lifespan="off")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        assert self.server.started, "uvicorn did not start in time"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _sign(body: bytes, timestamp: str, secret: str = CF_SECRET) -> str:
    signed = f"{timestamp}{body.decode()}".encode()
    return base64.b64encode(
        hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    ).decode()


def _webhook_body(order_id: str, amount: float, payment_id: str) -> bytes:
    return json.dumps({
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id},
            "payment": {"payment_status": "SUCCESS",
                       "payment_amount": amount,
                       "cf_payment_id": payment_id,
                       "payment_method": {"upi": {"upi_id": "cust@okaxis"}}},
        },
    }).encode()


@pytest.fixture(scope="module")
def real_server():
    srv = _RealServer()
    srv.start()
    yield srv
    srv.stop()


class TestWebhookConcurrencyOverRealHTTP:
    async def test_two_identical_webhooks_exactly_one_paid_transition(
            self, seed, real_server, monkeypatch):
        """20 trials. Each trial: one order, one gateway_payment_id, two
        byte-identical signed webhooks fired concurrently at the real server.

        EVERYTHING here — order creation, both webhooks, and verification —
        goes over the real server's own event loop (the uvicorn thread's),
        never through the ASGITransport `client` fixture's loop. Mixing the
        two against the SAME SQLAlchemy engine was tried first and failed
        with asyncpg's `RuntimeError: Future ... attached to a different
        loop` — a cross-loop pooled-connection artifact of this test's own
        plumbing, not a server bug. app.core.database.engine is disposed
        before the server starts so its pool holds no connection left over
        from `seed`'s own setup (which does run on the ASGITransport loop).
        """
        from app.core.database import engine as _db_engine
        await _db_engine.dispose()

        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)

        winners = []
        losers = []
        fivexx = []

        async with httpx.AsyncClient(base_url=real_server.base_url,
                                     timeout=15.0) as http:
            for trial in range(TRIALS):
                # Order created under the stub (conftest default), over the
                # real server, so it lands on the SAME loop/pool as the
                # webhooks that follow.
                monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
                r = await http.post(
                    f"{API}/customer/orders", headers=seed["customer_auth"],
                    json={"outlet_id": seed["outlet_id"],
                          "items": [{"menu_item_id": seed["menu_item_id"],
                                     "quantity": 1}]})
                assert r.status_code == 200, r.text
                order = r.json()

                # Flip to cashfree for exactly the two real HTTP POSTs that
                # follow — the uvicorn thread reads the SAME settings object.
                monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")

                payment_id = f"cfpay_concurrency_{trial}_{order['id'][:8]}"
                body = _webhook_body(order["id"], order["total_amount"],
                                     payment_id)
                ts = str(int(time.time()))
                sig = _sign(body, ts)
                headers = {"content-type": "application/json",
                          "x-webhook-signature": sig,
                          "x-webhook-timestamp": ts}

                results = await asyncio.gather(
                    http.post(f"{API}/customer/payment/webhook",
                             content=body, headers=headers),
                    http.post(f"{API}/customer/payment/webhook",
                             content=body, headers=headers),
                    return_exceptions=True,
                )

                statuses = []
                for res in results:
                    if isinstance(res, Exception):
                        statuses.append(f"EXC:{res!r}")
                        continue
                    statuses.append(res.status_code)
                    if res.status_code >= 500:
                        fivexx.append((trial, res.status_code, res.text))

                codes = [s for s in statuses if isinstance(s, int)]
                assert all(c == 200 for c in codes), (
                    f"trial {trial}: expected both webhooks to answer 200 "
                    f"(one real transition, one idempotent echo), got {statuses}")

                winners.append(min(statuses) if statuses else None)
                losers.append(max(statuses) if statuses else None)

                # Verify over the SAME real server — exactly one PAID
                # transition, one code, one points accrual.
                order_resp = await http.get(
                    f"{API}/customer/orders/{order['id']}",
                    headers=seed["customer_auth"])
                assert order_resp.status_code == 200, order_resp.text
                order_state = order_resp.json()
                assert order_state["payment_status"] == "PAID"
                assert order_state.get("pickup_code")

                points_resp = await http.get(
                    f"{API}/customer/points", headers=seed["customer_auth"])
                assert points_resp.status_code == 200, points_resp.text
                accruals = [t for t in points_resp.json()["transactions"]
                           if t.get("order_id") == order["id"]
                           and t.get("reason") == "ORDER_ACCRUAL"]
                assert len(accruals) == 1, (
                    f"trial {trial}: expected exactly one ORDER_ACCRUAL row "
                    f"for this order, got {len(accruals)}")

        # Literal status codes of the winner and the loser, both webhooks
        # being identical requests — report what actually happened.
        print(f"\n[Task 3c] {TRIALS} trials. Winner status codes: {winners}")
        print(f"[Task 3c] {TRIALS} trials. Loser status codes: {losers}")

        # Dispose again on the way out: every connection this test created
        # lives on the real_server thread's event loop, which is about to be
        # torn down with that thread. Any test file that runs after this one
        # in the SAME pytest process must not inherit those now-orphaned
        # connections from the pool — it would try to use a socket bound to
        # a dead loop and fail with errors unrelated to whatever it is
        # actually testing.
        await _db_engine.dispose()

        assert not fivexx, f"5xx responses observed: {fivexx}"
