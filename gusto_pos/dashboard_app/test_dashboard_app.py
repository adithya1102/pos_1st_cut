"""Tests for the login-gated dashboard proxy.

Holds:
  * login rejects wrong creds, accepts correct ones, session persists, and
    protected routes 401 without a session;
  * the proxy attaches X-Testing-Key on the OUTBOUND call to the backend;
  * that key NEVER appears in anything sent to the browser (login page,
    dashboard page, or any /api/* response) — asserted by grepping response
    bodies for the secret string.

The backend is a MockTransport, so these run with no real backend and can
inspect exactly what header the proxy sent outward.
"""
import os

import httpx
import pytest
from fastapi.testclient import TestClient

import main

KEY = "SUPER-SECRET-TESTING-KEY-9z9z"   # distinctive, so we can grep for leaks
# Test-local credentials — deliberately NOT the real ones. The test sets these
# as the app's env and logs in with them, so the suite never encodes the
# production password.
USER = "test-user"
PASS = "test-pass-xyz"


@pytest.fixture(autouse=True)
def _env_and_backend(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", USER)
    monkeypatch.setenv("DASHBOARD_PASS", PASS)
    monkeypatch.setenv("TESTING_DASHBOARD_KEY", KEY)
    monkeypatch.setenv("BACKEND_URL", "https://backend.example.com")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")

    sent_headers: list[dict] = []
    # Full outbound URLs, so a test can assert the query string the proxy built
    # (the day filter) and not just the headers it attached.
    sent_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent_headers.append({k.lower(): v for k, v in request.headers.items()})
        sent_urls.append(str(request.url))
        p = request.url.path
        if p.endswith("/orders"):
            return httpx.Response(200, json=[
                {"order_id": "o1", "outlet_id": "ou1", "outlet_name": "R1",
                 "status": "READY", "payment_status": "PAID", "pickup_code": "482913",
                 "identifier": "+919812345678", "label": None, "items": []}])
        if p.endswith("/outlets"):
            return httpx.Response(200, json=[
                {"id": "ou1", "name": "R1", "order_status": "open",
                 "is_manually_closed": False, "opening_time": None,
                 "closing_time": None}])
        if p.endswith("/compliance"):
            return httpx.Response(200, json={
                "ordered": [], "not_ordered": [],
                "window_start_utc": "2026-01-01T00:00:00Z",
                "window_end_utc": "2026-01-02T00:00:00Z"})
        return httpx.Response(200, json={"ok": True, "echo_path": p})

    transport = httpx.MockTransport(handler)

    def fake_client():
        return httpx.AsyncClient(
            base_url=os.environ["BACKEND_URL"].rstrip("/") + "/api/v1/testing",
            headers={"X-Testing-Key": os.environ["TESTING_DASHBOARD_KEY"]},
            transport=transport, timeout=5)

    monkeypatch.setattr(main, "_backend_client", fake_client)
    # Expose the recorders to tests.
    main._TEST_SENT_HEADERS = sent_headers  # type: ignore[attr-defined]
    main._TEST_SENT_URLS = sent_urls        # type: ignore[attr-defined]
    yield sent_headers


def _client():
    return TestClient(main.app, follow_redirects=False)


def _login(c):
    return c.post("/login", data={"username": USER, "password": PASS})


class TestLogin:
    def test_wrong_password_rejected(self):
        c = _client()
        r = c.post("/login", data={"username": USER, "password": "nope"})
        assert r.status_code == 303
        assert r.headers["location"] == "/login?error=1"
        # No session → dashboard bounces to login.
        assert c.get("/").headers["location"] == "/login"

    def test_unknown_user_rejected(self):
        c = _client()
        r = c.post("/login", data={"username": "hacker", "password": PASS})
        assert r.headers["location"] == "/login?error=1"

    def test_correct_credentials_accepted_and_session_persists(self):
        c = _client()
        r = _login(c)
        assert r.status_code == 303 and r.headers["location"] == "/"
        # Session cookie now lets the dashboard render...
        home = c.get("/")
        assert home.status_code == 200
        assert "Testing Dashboard" in home.text
        # ...and persists across further requests without re-auth.
        assert c.get("/api/orders").status_code == 200

    def test_fail_closed_when_creds_unset(self, monkeypatch):
        # Even submitting the usual creds must fail while the SERVER has none
        # configured — the dashboard never becomes open by omission.
        monkeypatch.delenv("DASHBOARD_USER", raising=False)
        monkeypatch.delenv("DASHBOARD_PASS", raising=False)
        c = _client()
        r = c.post("/login", data={"username": USER, "password": PASS})
        assert r.headers["location"] == "/login?error=1"
        assert c.get("/").headers["location"] == "/login"

    def test_logout_clears_session(self):
        c = _client()
        _login(c)
        assert c.get("/api/orders").status_code == 200
        c.get("/logout")
        # After logout the API guard rejects again.
        assert c.get("/api/orders").status_code == 401


class TestProtectedRoutes:
    def test_api_routes_401_without_session(self):
        c = _client()
        for path in ["/api/outlets", "/api/orders", "/api/testers", "/api/compliance"]:
            assert c.get(path).status_code == 401, path

    def test_dashboard_redirects_without_session(self):
        c = _client()
        r = c.get("/")
        assert r.status_code == 303 and r.headers["location"] == "/login"


class TestProxyAttachesKey:
    def test_outbound_request_carries_the_key(self, _env_and_backend):
        c = _client()
        _login(c)
        c.get("/api/orders")
        sent = _env_and_backend
        assert sent, "proxy never called the backend"
        assert sent[-1].get("x-testing-key") == KEY, \
            "the proxy must attach X-Testing-Key on the backend call"


class TestOrderActions:
    def test_approve_proxies_to_backend_with_key(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.post("/api/orders/o1/approve")
        assert r.status_code == 200
        assert _env_and_backend[-1].get("x-testing-key") == KEY
        assert r.json()["echo_path"].endswith("/orders/o1/approve")

    def test_reject_proxies_body_to_backend_with_key(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.post("/api/orders/o1/reject", json={"reason": "wrong order"})
        assert r.status_code == 200
        assert _env_and_backend[-1].get("x-testing-key") == KEY
        assert r.json()["echo_path"].endswith("/orders/o1/reject")

    def test_ready_proxies_to_backend_with_key(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.post("/api/orders/o1/ready")
        assert r.status_code == 200
        assert _env_and_backend[-1].get("x-testing-key") == KEY
        # The backend's own /ready route, not approve with a parameter.
        assert r.json()["echo_path"].endswith("/orders/o1/ready")

    def test_deliver_proxies_to_backend_with_key(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.post("/api/orders/o1/deliver")
        assert r.status_code == 200
        assert _env_and_backend[-1].get("x-testing-key") == KEY
        assert r.json()["echo_path"].endswith("/orders/o1/deliver")

    def test_actions_require_a_session(self):
        c = _client()
        assert c.post("/api/orders/o1/approve").status_code == 401
        assert c.post("/api/orders/o1/ready").status_code == 401
        assert c.post("/api/orders/o1/deliver").status_code == 401
        assert c.post("/api/orders/o1/reject", json={}).status_code == 401

    def test_actions_do_not_leak_the_key(self, _env_and_backend):
        c = _client(); _login(c)
        assert KEY not in c.post("/api/orders/o1/approve").text
        assert KEY not in c.post("/api/orders/o1/ready").text
        assert KEY not in c.post("/api/orders/o1/deliver").text
        assert KEY not in c.post("/api/orders/o1/reject", json={"reason": "x"}).text


class TestDayFilterPassthrough:
    def test_day_is_forwarded_to_the_backend(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.get("/api/orders?day=2026-09-01")
        assert r.status_code == 200
        assert _env_and_backend[-1].get("x-testing-key") == KEY
        assert main._TEST_SENT_URLS[-1].endswith("/orders?day=2026-09-01")

    def test_no_day_means_no_query_string(self, _env_and_backend):
        # The proxy neither interprets nor defaults the day: an omitted day is
        # forwarded as an omitted day, so the BACKEND decides what "today" is.
        # Defaulting here too would give the tool two definitions of today, in
        # two timezones.
        c = _client(); _login(c)
        assert c.get("/api/orders").status_code == 200
        assert main._TEST_SENT_URLS[-1].endswith("/orders")


class TestReadyButtonIsWired:
    """The page is served as a static template with no JS test harness, so the
    wiring is asserted at the source level: the button must be gated on the
    server-computed can_ready and must call the /ready route."""

    def test_dashboard_renders_a_ready_button_gated_on_can_ready(self):
        c = _client(); _login(c)
        page = c.get("/").text
        assert "o.can_ready" in page, \
            "the Ready button must be gated on the server flag, not the status text"
        assert ">Ready</button>" in page
        assert "/ready'" in page or "/ready\"" in page

    def test_dashboard_renders_a_delivered_button_gated_on_can_deliver(self):
        c = _client(); _login(c)
        page = c.get("/").text
        assert "o.can_deliver" in page
        assert ">Delivered</button>" in page
        assert "/deliver'" in page or "/deliver\"" in page

    def test_all_four_actions_are_present(self):
        c = _client(); _login(c)
        page = c.get("/").text
        for label in ("Approve", "Ready", "Delivered", "Reject"):
            assert f">{label}</button>" in page, f"{label} button is missing"


class TestFlatTableAndDayPicker:
    """The page must not regroup by restaurant, must not re-sort, and must
    default the day picker to today IST."""

    def test_orders_are_not_grouped_by_outlet(self):
        c = _client(); _login(c)
        page = c.get("/").text
        # The old grouping built a map of orders keyed by outlet and rendered a
        # section per outlet. Its absence is the change.
        assert "byOutlet" not in page, "orders are still being grouped by outlet"
        assert "<th>Restaurant</th>" in page, \
            "the restaurant must survive as a column"

    def test_the_page_does_not_re_sort_the_server_order(self):
        c = _client(); _login(c)
        page = c.get("/").text
        # Re-sorting client-side would be a second definition of "newest",
        # free to disagree with the server's ORDER BY.
        assert ".sort(" not in page

    def test_day_picker_defaults_to_ist_today(self):
        c = _client(); _login(c)
        page = c.get("/").text
        assert 'id="day"' in page
        assert "Asia/Kolkata" in page, \
            "today must be computed in IST, not the device's timezone"
        assert "istToday()" in page


class TestTerminalStatusesAreLegible:
    """Finished orders are visible in the day view now, so they need to read as
    finished — and must not carry actions."""

    def test_every_terminal_status_has_its_own_pill_style(self):
        c = _client(); _login(c)
        page = c.get("/").text
        for status in ("COMPLETED", "CANCELLED", "ABANDONED"):
            assert f".pill.{status}" in page, \
                f"{status} would render as an unstyled pill"

    def test_finished_rows_are_marked_done(self):
        c = _client(); _login(c)
        page = c.get("/").text
        # The row class is what dims the spent code; the list it is derived
        # from must cover every terminal status the backend can return.
        assert "isDone(o) ? 'done' : ''" in page
        for status in ("COMPLETED", "CANCELLED", "ABANDONED"):
            assert f"'{status}'" in page

    def test_buttons_still_come_only_from_the_server_flags(self):
        # The presentation list must NOT be what decides actions — otherwise a
        # status missing from it would put live buttons on a dead order. Every
        # button stays gated on its can_* flag.
        c = _client(); _login(c)
        page = c.get("/").text
        for flag in ("o.can_approve", "o.can_ready", "o.can_deliver",
                     "o.can_reject"):
            assert flag in page
        assert "DONE.includes" in page and "actionButtons" in page
        # isDone is used for styling only, never to add a button.
        assert "isDone(o) ?" in page and "if (isDone" not in page

    def test_ready_does_not_touch_the_otp_cell(self):
        # The pickup_code cell is rendered from o.pickup_code and nothing in the
        # Ready path may alter that — OTP visibility is out of scope.
        c = _client(); _login(c)
        page = c.get("/").text
        assert "esc(o.pickup_code)" in page, \
            "the OTP cell must still render straight from the order's code"


class TestKeyNeverReachesBrowser:
    def test_login_page_has_no_key(self):
        assert KEY not in _client().get("/login").text

    def test_dashboard_page_has_no_key(self):
        c = _client(); _login(c)
        assert KEY not in c.get("/").text

    def test_api_responses_have_no_key(self):
        c = _client(); _login(c)
        for path in ["/api/outlets", "/api/orders", "/api/compliance"]:
            body = c.get(path).text
            assert KEY not in body, f"{path} leaked the key to the browser"

    def test_label_patch_proxies_without_leaking(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.patch("/api/labels/+919812345678", json={"label": "Asha"})
        assert r.status_code == 200
        assert KEY not in r.text
        # And the outbound call to the backend still carried the key.
        assert _env_and_backend[-1].get("x-testing-key") == KEY
