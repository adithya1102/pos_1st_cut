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

    async def handler(request: httpx.Request) -> httpx.Response:
        sent_headers.append({k.lower(): v for k, v in request.headers.items()})
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
    # Expose the recorder to tests.
    main._TEST_SENT_HEADERS = sent_headers  # type: ignore[attr-defined]
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
