"""Forgot-password: does a reset actually reach the owner, and can they spend it?

## The bug these hold the line on
`AccountService._deliver` had no transport. With EMAIL_ENABLED false it logged
and dropped the mail; with EMAIL_ENABLED **true** it logged a warning and still
dropped it, because there was no `else` branch that sent anything. A token was
minted and committed on every request and no owner ever received one, so
forgot-password was a dead end on every deploy — and the endpoint cheerfully
answered "we've sent reset instructions" each time.

The SMTP conversation itself is stubbed here (`_send_smtp_blocking` is replaced),
because what is being tested is that the pipeline REACHES the transport carrying
a usable token — not that smtplib can talk to a mail server.
"""
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.account.service import AccountService

API = "/api/v1"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def outbox(monkeypatch):
    """Captures what would have gone out, and turns mail on.

    Patching `_send_smtp_blocking` (not `_deliver`) keeps the real `_deliver`
    in the path — its config gate, its to_thread hop and its failure handling
    are all part of what is under test.
    """
    sent: list[dict] = []

    def _capture(to: str, subject: str, body: str) -> None:
        sent.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(AccountService, "_send_smtp_blocking", staticmethod(_capture))
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "EMAIL_SMTP_HOST", "smtp.test.invalid")
    return sent


@pytest.fixture
def no_mail(monkeypatch):
    """A deploy with no mail transport — the state prod is actually in."""
    monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    monkeypatch.setattr(settings, "EMAIL_SMTP_HOST", "")


async def _give_owner_an_email(db, seed, address: str) -> None:
    await db.execute(text("UPDATE users SET email = :e WHERE id = :uid"),
                     {"e": address, "uid": seed["owner_id"]})
    await db.commit()


def _code_from(body: str) -> str:
    """The reset code as the owner reads it off the mail."""
    m = re.search(r"reset code is:\s*(\S+)", body)
    assert m, f"no code in the mail body:\n{body}"
    return m.group(1)


class TestMailIsActuallySent:
    async def test_a_reset_request_reaches_the_transport(self, client, seed, db, outbox):
        """THE regression. This assertion failed before the fix: the request
        returned 200, the token was written, and outbox stayed empty."""
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")

        r = await client.post(f"{API}/auth/password/forgot",
                              json={"username": seed["owner_username"]})
        assert r.status_code == 200, r.text
        assert len(outbox) == 1, "the reset mail was never handed to a transport"
        assert outbox[0]["to"] == f"{seed['tag']}@example.com"

    async def test_the_mail_carries_a_code_that_works(self, client, seed, db, outbox):
        """A sent mail is worthless if what it carries cannot be redeemed."""
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        await client.post(f"{API}/auth/password/forgot",
                          json={"username": seed["owner_username"]})

        code = _code_from(outbox[0]["body"])
        r = await client.post(f"{API}/auth/password/reset",
                              json={"token": code, "new_password": "brand-new-pw-9"})
        assert r.status_code == 200, r.text

    async def test_the_owner_can_sign_in_with_the_new_password(
        self, client, seed, db, outbox
    ):
        """End to end, the whole point of the feature: locked out -> signed in."""
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        await client.post(f"{API}/auth/password/forgot",
                          json={"username": seed["owner_username"]})
        code = _code_from(outbox[0]["body"])
        await client.post(f"{API}/auth/password/reset",
                          json={"token": code, "new_password": "brand-new-pw-9"})

        ok = await client.post(f"{API}/auth/login", data={
            "username": seed["owner_username"], "password": "brand-new-pw-9"})
        assert ok.status_code == 200, ok.text
        assert ok.json().get("access_token")

        # And the old one is genuinely dead, not merely superseded.
        old = await client.post(f"{API}/auth/login", data={
            "username": seed["owner_username"], "password": "correct-horse"})
        assert old.status_code == 401

    async def test_the_code_is_single_use(self, client, seed, db, outbox):
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        await client.post(f"{API}/auth/password/forgot",
                          json={"username": seed["owner_username"]})
        code = _code_from(outbox[0]["body"])

        first = await client.post(f"{API}/auth/password/reset",
                                  json={"token": code, "new_password": "first-pw-12345"})
        assert first.status_code == 200
        again = await client.post(f"{API}/auth/password/reset",
                                  json={"token": code, "new_password": "second-pw-12345"})
        assert again.status_code == 400, "a spent code must not reopen the account"

    async def test_an_expired_code_is_refused(self, client, seed, db, outbox):
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        await client.post(f"{API}/auth/password/forgot",
                          json={"username": seed["owner_username"]})
        code = _code_from(outbox[0]["body"])

        await db.execute(text("""
            UPDATE auth_tokens SET expires_at = now() - interval '1 minute'
            WHERE user_id = :uid AND kind = 'PASSWORD_RESET'
        """), {"uid": seed["owner_id"]})
        await db.commit()

        r = await client.post(f"{API}/auth/password/reset",
                              json={"token": code, "new_password": "too-late-pw-123"})
        assert r.status_code == 400

    async def test_a_dead_mail_server_does_not_destroy_the_token(
        self, client, seed, db, monkeypatch, outbox
    ):
        """Delivery used to be awaited BEFORE the commit, so a throwing
        transport rolled back the very token it was carrying and the owner got
        a 500. The token is now committed first and `_deliver` swallows the
        failure, so the request still succeeds and the code stays redeemable —
        which matters because an admin can read it out of the DB."""
        def _boom(to, subject, body):
            raise OSError("mail server refused the connection")

        monkeypatch.setattr(AccountService, "_send_smtp_blocking", staticmethod(_boom))
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")

        r = await client.post(f"{API}/auth/password/forgot",
                              json={"username": seed["owner_username"]})
        assert r.status_code == 200, "an SMTP outage is not the owner's error"

        n = await db.scalar(text("""
            SELECT count(*) FROM auth_tokens
            WHERE user_id = :uid AND kind = 'PASSWORD_RESET' AND used_at IS NULL
        """), {"uid": seed["owner_id"]})
        assert n == 1, "the token must survive a failed send"


class TestItNeverPromisesMailItCannotSend:
    async def test_unconfigured_server_says_so(self, client, seed, db, no_mail):
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        r = await client.post(f"{API}/auth/password/forgot",
                              json={"username": seed["owner_username"]})
        body = r.json()

        assert body["email_configured"] is False
        assert body["needs_admin_help"] is True, "the admin queue is the only route"
        assert "not configured" in body["message"].lower()
        assert "we've sent" not in body["message"].lower()

    async def test_configured_server_does_promise(self, client, seed, db, outbox):
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        r = await client.post(f"{API}/auth/password/forgot",
                              json={"username": seed["owner_username"]})
        assert r.json()["email_configured"] is True

    async def test_email_configured_needs_both_switches(self, monkeypatch):
        """EMAIL_ENABLED alone was never enough — that was the trap the old code
        fell into. A host with the flag off is equally inert."""
        monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
        monkeypatch.setattr(settings, "EMAIL_SMTP_HOST", "")
        assert AccountService.email_configured() is False

        monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
        monkeypatch.setattr(settings, "EMAIL_SMTP_HOST", "smtp.test.invalid")
        assert AccountService.email_configured() is False

        monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
        monkeypatch.setattr(settings, "EMAIL_SMTP_HOST", "smtp.test.invalid")
        assert AccountService.email_configured() is True


class TestItStillGivesNothingAwayForFree:
    async def test_unknown_username_is_a_200_and_sends_nothing(self, client, outbox):
        r = await client.post(f"{API}/auth/password/forgot",
                              json={"username": "no-such-owner-anywhere"})
        assert r.status_code == 200
        assert r.json()["email_hint"] is None
        assert outbox == [], "nothing may be sent for an account that does not exist"

    async def test_email_configured_does_not_vary_by_username(
        self, client, seed, db, outbox
    ):
        """The one flag added to this response must stay a property of the
        DEPLOY. If it ever tracked the account it would become an enumeration
        oracle."""
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        real = await client.post(f"{API}/auth/password/forgot",
                                 json={"username": seed["owner_username"]})
        fake = await client.post(f"{API}/auth/password/forgot",
                                 json={"username": "no-such-owner-anywhere"})
        assert real.json()["email_configured"] == fake.json()["email_configured"]

    async def test_the_response_shape_is_identical(self, client, seed, db, outbox):
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        real = await client.post(f"{API}/auth/password/forgot",
                                 json={"username": seed["owner_username"]})
        fake = await client.post(f"{API}/auth/password/forgot",
                                 json={"username": "no-such-owner-anywhere"})
        assert set(real.json()) == set(fake.json())

    async def test_a_reset_is_capped_per_hour(self, client, seed, db, outbox):
        """The cap is what stops this endpoint being used to spray someone's
        inbox. Past it, nothing more is sent."""
        await _give_owner_an_email(db, seed, f"{seed['tag']}@example.com")
        for _ in range(8):
            await client.post(f"{API}/auth/password/forgot",
                              json={"username": seed["owner_username"]})
        assert len(outbox) == 5, "RESET_MAX_PER_HOUR must bound what goes out"
