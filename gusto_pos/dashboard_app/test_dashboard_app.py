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
import re

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
        if p.endswith("/scheduled"):
            # One held order, shaped exactly as the backend's
            # TestingService.scheduled_orders returns it.
            return httpx.Response(200, json=[
                {"order_id": "o9", "outlet_id": "ou1", "outlet_name": "R1",
                 "identifier": "+919812345678", "label": None,
                 "pickup_code": "771204", "status": "PAID",
                 "payment_status": "PAID", "state": "held",
                 "requested_pickup_at": "2026-09-17T14:00:00+00:00",
                 "requested_pickup_at_ist": "2026-09-17 19:30",
                 "release_at": "2026-09-17T13:46:00+00:00",
                 "release_at_ist": "2026-09-17 19:16",
                 "seconds_until_release": 840, "is_due": False,
                 "mu_ready_s": 420, "mu_source": "order_twin",
                 "implied_mu_s": 420, "safety_margin_s": 420, "lead_s": 840,
                 "model_version": "release_v1", "decisions": 1,
                 "last_decision": "held",
                 "last_decision_at": "2026-09-17T11:00:00+00:00",
                 "last_decision_at_ist": "2026-09-17 16:30",
                 "released_at": None, "released_at_ist": None,
                 "created_at_ist": "2026-09-17 16:30"}])
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
    # base_url is HTTPS deliberately. The session cookie is set with
    # https_only=True (Secure), so a client talking to http://testserver is
    # handed the cookie and silently discards it — every subsequent request
    # arrives unauthenticated and every page assertion sees the body of a 303.
    #
    # Pointing the test client at https:// models what the browser actually
    # does (Render serves the dashboard over TLS) rather than relaxing the
    # cookie to suit the harness.
    return TestClient(main.app, base_url="https://testserver",
                      follow_redirects=False)


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


class TestScheduledSectionIsProxied:
    """The Scheduled-pickups section goes through the SAME proxy contract as
    every other read: session required, key attached outbound, key never
    returned inward, day forwarded verbatim."""

    def test_it_requires_a_session(self):
        assert _client().get("/api/scheduled").status_code == 401

    def test_the_outbound_call_carries_the_key(self, _env_and_backend):
        c = _client(); _login(c)
        r = c.get("/api/scheduled")
        assert r.status_code == 200
        assert _env_and_backend[-1].get("x-testing-key") == KEY
        assert main._TEST_SENT_URLS[-1].endswith("/scheduled")

    def test_the_response_does_not_leak_the_key(self):
        c = _client(); _login(c)
        assert KEY not in c.get("/api/scheduled").text

    def test_the_engine_numbers_survive_the_proxy(self):
        """The proxy hands the browser the data unchanged — the section is
        useless if the numbers behind the release moment are dropped on the
        way through."""
        c = _client(); _login(c)
        row = c.get("/api/scheduled").json()[0]
        assert row["state"] == "held"
        assert row["mu_ready_s"] == 420
        assert row["safety_margin_s"] == 420
        assert row["lead_s"] == 840
        assert row["seconds_until_release"] == 840
        assert row["pickup_code"] == "771204"

    def test_day_is_forwarded_verbatim(self, _env_and_backend):
        c = _client(); _login(c)
        assert c.get("/api/scheduled?day=2026-09-01").status_code == 200
        assert main._TEST_SENT_URLS[-1].endswith("/scheduled?day=2026-09-01")

    def test_no_day_means_no_query_string(self, _env_and_backend):
        # Same reasoning as /api/orders: the backend owns the definition of
        # "today", and defaulting here would create a second one.
        c = _client(); _login(c)
        assert c.get("/api/scheduled").status_code == 200
        assert main._TEST_SENT_URLS[-1].endswith("/scheduled")


class TestScheduledSectionIsWiredIntoThePage:
    """Source-level, like the button tests: the page is a static template with
    no JS harness, so the wiring is asserted by reading it."""

    def _page(self):
        c = _client(); _login(c)
        return c.get("/").text

    def test_the_section_exists_and_is_fetched_every_round(self):
        page = self._page()
        assert "Scheduled pickups" in page
        assert "id=\"scheduled\"" in page
        assert "/api/scheduled" in page, \
            "the refresh round must actually fetch the section"

    def test_every_required_column_is_rendered(self):
        """requested_pickup_at, the computed release_at, mu, the margin, the
        state, and the time remaining — the six things the section exists to
        show."""
        page = self._page()
        for field in ("requested_pickup_at_ist", "release_at_ist",
                      "safety_margin_s", "mu_ready_s", "o.state",
                      "seconds_until_release"):
            assert field in page, f"{field} is missing from the section"

    def test_the_countdown_is_anchored_to_the_servers_number(self):
        """NOT to release_at minus the browser clock. A laptop a few minutes
        off would otherwise disagree with the backend about whether an order
        is due — and being able to trust the displayed moment is the entire
        point of this section."""
        page = self._page()
        assert "seconds_until_release" in page
        assert "scheduledFetchedAt" in page, \
            "the ticker must count elapsed time since the fetch"
        assert "Date.parse(o.release_at)" not in page
        assert "new Date(o.release_at)" not in page

    def test_the_countdown_ticks_between_polls(self):
        page = self._page()
        assert "tickCountdowns" in page
        assert "setInterval(tickCountdowns, 1000)" in page

    def test_the_section_renders_even_while_a_label_is_being_edited(self):
        """It holds no inputs to protect, and freezing a countdown because
        someone is naming a tester elsewhere would be a bug."""
        page = self._page()
        refresh = page[page.index("async function refreshAll"):]
        # The body of `if (!editing) { … }` — the block that is skipped mid-edit.
        block = refresh[refresh.index("if (!editing)"):]
        block = block[: block.index("}") + 1]
        assert "render(orders)" in block, "sanity: found the right block"
        assert "renderScheduled" not in block, \
            "renderScheduled must sit OUTSIDE the editing guard"
        assert "renderScheduled(scheduled)" in refresh, \
            "…but it must still run every round"

    def test_a_held_row_shows_the_pickup_code(self):
        """The OTP column is on this table too — a held order having a code is
        the most counter-intuitive part of the feature."""
        page = self._page()
        start = page.index("function renderScheduled")
        section = page[start: page.index("function renderOutlets", start)]
        assert "o.pickup_code" in section
        assert "<th>OTP</th>" in section

    def test_states_are_styled_so_held_reads_differently_from_released(self):
        page = self._page()
        assert ".pill.held" in page and ".pill.released" in page


class TestReadyButtonIsWired:
    """The page is served as a static template with no JS test harness, so the
    wiring is asserted at the source level: the button must be gated on the
    server-computed can_ready and must call the /ready route.

    The buttons are now built by a `btn(action, label)` helper and dispatched
    by a delegated listener, rather than each carrying an inline
    `onclick="fn('<id>')"`. The old assertions looked for the literal
    `>Ready</button>`, which only existed while the label was inlined into the
    template string. Intent is unchanged: gated on the server flag, wired to
    the right route, all four present.
    """

    def test_dashboard_renders_a_ready_button_gated_on_can_ready(self):
        c = _client(); _login(c)
        page = c.get("/").text
        assert "o.can_ready" in page, \
            "the Ready button must be gated on the server flag, not the status text"
        assert "btn('ready'" in page, "the Ready button is no longer built"
        assert "'Ready'" in page
        assert "/ready'" in page or "/ready\"" in page

    def test_dashboard_renders_a_delivered_button_gated_on_can_deliver(self):
        c = _client(); _login(c)
        page = c.get("/").text
        assert "o.can_deliver" in page
        assert "btn('deliver'" in page, "the Delivered button is no longer built"
        assert "'Delivered'" in page
        assert "/deliver'" in page or "/deliver\"" in page

    def test_all_four_actions_are_present(self):
        c = _client(); _login(c)
        page = c.get("/").text
        for action, label in (("approve", "Approve"), ("ready", "Ready"),
                              ("deliver", "Delivered"), ("reject", "Reject")):
            assert f"btn('{action}'" in page, f"{label} button is missing"
            assert f"'{label}'" in page, f"{label} label is missing"
        # Every action must be reachable from the dispatch table, or the button
        # renders and does nothing.
        for action in ("approve", "ready", "deliver", "reject"):
            assert f"{action}:" in page, f"{action} is not in the ACTIONS map"

    def test_order_ids_never_reach_a_javascript_parsing_context(self):
        """Regression guard for the XSS shape this pass removed.

        `onclick="approveOrder('${esc(o.order_id)}')"` put server data inside a
        JS string literal nested in an HTML attribute. esc() did not escape ',
        so a quote in order_id closed the literal and the rest ran as script.

        Adding ' to esc() does NOT fix that context — the browser HTML-decodes
        an attribute value before the JS parser sees it, so &#39; decodes back
        to ' and breaks out identically. The fix was structural, and this
        asserts the structure rather than the escaping.
        """
        c = _client(); _login(c)
        page = c.get("/").text
        # Strip JS line comments so the explanatory note in the template (which
        # quotes the old shape verbatim) does not trip this.
        code = "\n".join(l for l in page.splitlines()
                         if not l.lstrip().startswith("//"))
        assert "onclick=\"approveOrder(" not in code
        assert "${esc(o.order_id)}')" not in code, \
            "an order id is being interpolated into an onclick again"
        assert "data-order-id=" in code, "buttons no longer carry the id as data"
        assert "closest('button[data-act][data-order-id]')" in code, \
            "the delegated dispatcher is gone"

    def test_esc_escapes_single_quotes(self):
        """Defence in depth for the ordinary attribute contexts."""
        c = _client(); _login(c)
        page = c.get("/").text
        assert "&#39;" in page, "esc() no longer escapes single quotes"


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


class TestTheRefreshLoopCannotOverlapItself:
    """The auto-refresh must not start a round while one is still in flight.

    It used to be `setInterval(() => { if (!editing) refreshAll(); }, 15000)`.
    A round fans out to THREE backend calls, and the backend is on Render's
    free plan where a cold start takes ~45s — so three ticks landed before the
    first replied and a single tab could hold nine requests open. The interval
    never asked whether the previous round had finished.

    These are STRUCTURAL assertions on the served page, matching how the rest
    of this file tests the template. They are not a browser run: what they pin
    is that the page cannot express the overlapping shape, because the fix is
    the control flow itself — one await chain, with the next timer armed only
    after the current round settles.
    """

    def _page(self):
        c = _client(); _login(c)
        return c.get("/").text

    def test_no_fixed_interval_drives_the_refresh(self):
        page = self._page()
        # An ALLOWLIST of what may be put on a fixed interval, not a page-wide
        # ban on the word.
        #
        # This started as `"setInterval(" not in page`, which was exactly right
        # while every timer on the page fetched something. The countdown ticker
        # then arrived: it fires every second and repaints a few text nodes,
        # makes no request, and cannot overlap anything — so a blanket ban would
        # have forced the one shape that genuinely wants an interval into a
        # self-scheduling chain for no reason.
        #
        # Narrowed rather than deleted, and narrowed to a whitelist rather than
        # a blacklist: setInterval(refreshAll, …) — the actual regression this
        # was written to catch — still fails, and so does any NEW timer, because
        # anything not named here fails by default.
        calls = re.findall(r"setInterval\(\s*([A-Za-z0-9_$.]+)", page)
        assert calls == ["tickCountdowns"], (
            "a fixed interval fires regardless of whether the previous round "
            "finished — that is exactly the overlap this removes. Only the "
            f"countdown repaint may be on one; found {calls}"
        )

    def test_the_one_permitted_interval_performs_no_network_call(self):
        """What earns tickCountdowns its exemption above, asserted rather than
        assumed: the moment it fetches anything it becomes the overlapping
        shape the loop exists to prevent, and this fails."""
        page = self._page()
        fn = page[page.index("function tickCountdowns"):]
        fn = fn[: fn.index("\n    }")]
        for forbidden in ("api(", "fetch(", "await "):
            assert forbidden not in fn, (
                f"tickCountdowns must stay a pure repaint — found {forbidden!r}")

    def test_the_next_round_is_scheduled_only_after_the_previous_awaits(self):
        page = self._page()
        assert "await refreshAll()" in page, (
            "the round must be awaited; calling it un-awaited reintroduces the "
            "overlap under a different function name"
        )
        assert "setTimeout(refreshLoop, 15000)" in page

    def test_the_await_comes_before_the_reschedule(self):
        # Ordering is the whole guarantee. Scheduling first and awaiting after
        # would still overlap, and would still contain both strings above.
        page = self._page()
        assert page.index("await refreshAll()") < page.index(
            "setTimeout(refreshLoop, 15000)"
        ), "the next round must be armed AFTER the current one settles"

    def test_a_failed_round_still_reschedules(self):
        # A throw escaping the loop would stop it forever and freeze the page
        # silently, which is worse than a stale read. The reschedule therefore
        # sits outside the try.
        page = self._page()
        loop = page[page.index("async function refreshLoop"):]
        loop = loop[: loop.index("setTimeout(refreshLoop, 15000)")]
        assert "try {" in loop and "catch" in loop, \
            "the awaited round must be wrapped so a throw cannot kill the loop"

    def test_an_open_edit_still_skips_the_round_but_keeps_the_cadence(self):
        # Behaviour preserved from the setInterval version: an in-progress
        # label edit must not be clobbered, but the loop must resume by itself.
        page = self._page()
        assert "if (!editing)" in page
        loop = page[page.index("async function refreshLoop"):]
        skip = loop.index("if (!editing)")
        arm = loop.index("setTimeout(refreshLoop, 15000)")
        assert skip < arm, \
            "the edit check must guard the round, not the rescheduling"


class TestReadsRetryTransientFailures:
    """A cold backend or a moment of edge throttling should not surface as an
    error the user has to act on — the page should just wait and try again.

    Structural assertions on the served page, as elsewhere in this file. The
    behaviour was verified separately by lifting the real api() out of the
    template and driving it with a stubbed fetch (429->200, persistent 429,
    5xx, 4xx, 2xx, POST, 401), with the pre-retry api() through the same
    harness as a control. What is pinned here is the shape that made those
    outcomes possible, so it cannot be quietly undone.
    """

    def _page(self):
        c = _client(); _login(c)
        return c.get("/").text

    def test_there_is_a_retry_budget_with_two_backoff_delays(self):
        page = self._page()
        assert "READ_RETRY_DELAYS = [3000, 8000]" in page, \
            "two retries, backing off — not a single immediate re-fire"

    def test_only_429_and_5xx_are_treated_as_transient(self):
        # A 4xx is the server rejecting the request itself. Repeating it gets
        # the same answer more slowly and buries the real cause in noise.
        page = self._page()
        assert "res.status === 429 || res.status >= 500" in page

    def test_mutating_calls_are_excluded_from_retry(self):
        # THE safety property. Every action on this page — approve, ready,
        # reject, deliver, saveLabel — goes through the same api() helper, and
        # a 5xx does not mean the server did nothing.
        page = self._page()
        assert "const isRead = !opts.method || opts.method.toUpperCase() === 'GET'" in page
        assert "const delays = isRead ? READ_RETRY_DELAYS : []" in page, \
            "a non-read must get an EMPTY budget, not a shorter one"

    def test_deliver_specifically_must_not_retry_a_429(self):
        # deliver runs the real verify_pickup, which answers 429 once an
        # outlet's pickup-miss cap is spent. Retrying would spend more of the
        # same budget and could lock the outlet out for other staff.
        page = self._page()
        assert "/deliver" in page and "method: 'POST'" in page, \
            "deliver must remain a POST so isRead excludes it from retry"

    def test_401_is_never_retried(self):
        # The session is gone; waiting does not bring it back.
        page = self._page()
        i401 = page.index("res.status === 401")
        itransient = page.index("const transient =")
        assert i401 < itransient, \
            "the 401 redirect must short-circuit before the retry decision"

    def test_the_error_only_surfaces_after_the_budget_is_spent(self):
        page = self._page()
        block = page[page.index("for (let attempt = 0"):page.index("const esc =")]
        assert "await sleep(delays[attempt])" in block and "continue;" in block
        assert block.index("continue;") < block.index("throw new Error(path"), \
            "the retry must be attempted before the throw that shows the error"
