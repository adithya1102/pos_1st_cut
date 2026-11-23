"""POS registration link: /owner/pos-registration-code, /pos-link/verify,
/pos-link/consume (migration 044).

Requires migration 044_pos_registration.sql applied to carevo_test (run
`python tests/reset_test_db.py`, which applies every migrations/*.sql file
in order — see that script's module docstring).

No HMAC / shared secret by design (see app/modules/pos_link/service.py's
module docstring): /pos-link/verify and /pos-link/consume are public, so
these tests cover code entropy's substitute protections -- rate limiting,
TTL, single-use, revocation on regenerate -- instead of a signature check.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from .conftest import API


@pytest.fixture(autouse=True)
def _reset_pos_link_rate_limit():
    """/pos-link/* failures are capped at 5/15min per IP by an in-process
    dict, and every test in this module shares one process and one client
    IP (httpx's ASGITransport has no real client address)."""
    from app.modules.pos_link import service as svc

    svc._pos_link_failure_hits.clear()
    yield
    svc._pos_link_failure_hits.clear()


@pytest.fixture(autouse=True)
async def _reset_global_failure_counter(db):
    """The DB-backed global backstop (pos_link_rate_limit_state) must start
    clean for every test, same reasoning as the in-memory reset above."""
    await db.execute(text(
        "UPDATE pos_link_rate_limit_state "
        "SET window_started_at = now(), failure_count = 0, cooldown_until = NULL "
        "WHERE id = 1"))
    await db.commit()
    yield


async def _pending_outlet(db, tag: str) -> dict:
    """A second outlet that has NOT been admin-approved -- verification_status
    stays at the self-signup default, 'pending_verification' (migration 003)."""
    org_id, outlet_id, owner_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(text(
        "INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
        {"i": str(org_id), "n": f"TEST_CAREVO_PendingOrg_{tag}"})
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                             upi_id, geofence_radius_meters, verification_status,
                             created_at)
        VALUES (:i,:o,:n,'Testville', true, 'test@upi', 150,
                'pending_verification', now())"""),
        {"i": str(outlet_id), "o": str(org_id),
         "n": f"TEST_CAREVO_PendingOutlet_{tag}"})
    from app.core.security import get_password_hash
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           is_outlet_owner, created_at)
        VALUES (:i,:u,:h, true, :o, true, now())"""),
        {"i": str(owner_id), "u": f"TEST_CAREVO_pending_owner_{tag}",
         "h": get_password_hash("correct-horse"), "o": str(outlet_id)})
    await db.commit()
    from app.core.auth import create_access_token
    return {
        "outlet_id": str(outlet_id),
        "owner_auth": {"Authorization": f"Bearer "
                       f"{create_access_token(subject=f'TEST_CAREVO_pending_owner_{tag}')}"},
    }


class TestMintRegistrationCode:
    @pytest.mark.asyncio
    async def test_approved_owner_can_mint_a_code(self, client, seed):
        r = await client.post(f"{API}/owner/pos-registration-code",
                               headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["code"].replace("-", "")) == 8
        assert "expires_at" in body

    @pytest.mark.asyncio
    async def test_unapproved_outlet_is_refused(self, client, db):
        pending = await _pending_outlet(db, uuid.uuid4().hex[:8])
        r = await client.post(f"{API}/owner/pos-registration-code",
                               headers=pending["owner_auth"])
        assert r.status_code == 403, r.text

    @pytest.mark.asyncio
    async def test_regenerating_revokes_the_old_code(self, client, seed, db):
        first = await client.post(f"{API}/owner/pos-registration-code",
                                   headers=seed["owner_auth"])
        assert first.status_code == 200, first.text
        old_code = first.json()["code"]

        second = await client.post(f"{API}/owner/pos-registration-code",
                                    headers=seed["owner_auth"])
        assert second.status_code == 200, second.text
        new_code = second.json()["code"]
        assert new_code != old_code

        # The old code must now fail verify with the SAME generic body.
        r = await client.post(f"{API}/pos-link/verify", json={"code": old_code})
        assert r.status_code == 400
        assert r.json()["detail"] == "Code not valid"

        # The new one must still work.
        r = await client.post(f"{API}/pos-link/verify", json={"code": new_code})
        assert r.status_code == 200, r.text


class TestVerify:
    @pytest.mark.asyncio
    async def test_valid_code_returns_outlet_and_owner(self, client, seed):
        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        code = mint.json()["code"]

        r = await client.post(f"{API}/pos-link/verify", json={"code": code})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["outlet"]["outlet_id"] == seed["outlet_id"]
        assert body["owner"]["name"] == seed["owner_username"]
        assert "registration_ref" in body and body["registration_ref"]

    @pytest.mark.asyncio
    async def test_wrong_code_returns_generic_400(self, client, seed):
        r = await client.post(f"{API}/pos-link/verify", json={"code": "ZZZZ-9999"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Code not valid"

    @pytest.mark.asyncio
    async def test_expired_code_returns_generic_400(self, client, seed, db):
        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        code = mint.json()["code"]
        await db.execute(text(
            "UPDATE pos_registration_codes SET expires_at = now() - interval '1 second' "
            "WHERE outlet_id = :o"), {"o": seed["outlet_id"]})
        await db.commit()

        r = await client.post(f"{API}/pos-link/verify", json={"code": code})
        assert r.status_code == 400
        assert r.json()["detail"] == "Code not valid"

    @pytest.mark.asyncio
    async def test_verify_does_not_consume_the_code(self, client, seed):
        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        code = mint.json()["code"]

        first = await client.post(f"{API}/pos-link/verify", json={"code": code})
        assert first.status_code == 200, first.text
        second = await client.post(f"{API}/pos-link/verify", json={"code": code})
        assert second.status_code == 200, second.text  # still verifiable

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self, client, seed):
        for _ in range(5):
            r = await client.post(f"{API}/pos-link/verify", json={"code": "ZZZZ-9999"})
            assert r.status_code == 400
        r = await client.post(f"{API}/pos-link/verify", json={"code": "ZZZZ-9999"})
        assert r.status_code == 429, r.text

    @pytest.mark.asyncio
    async def test_rate_limit_429_has_retry_after_header(self, client, seed):
        """Every other rate limiter in this codebase (check_login_rate_limit,
        check_test_push_rate_limit, check_pickup_miss_limit) sends
        Retry-After on its 429 -- this one must too, so a client can back
        off correctly instead of hammering the endpoint blind."""
        for _ in range(5):
            r = await client.post(f"{API}/pos-link/verify", json={"code": "ZZZZ-9999"})
            assert r.status_code == 400
        r = await client.post(f"{API}/pos-link/verify", json={"code": "ZZZZ-9999"})
        assert r.status_code == 429, r.text
        assert "retry-after" in {k.lower() for k in r.headers.keys()}, (
            "429 response is missing a Retry-After header"
        )


class TestConsume:
    @pytest.mark.asyncio
    async def test_reused_code_is_refused_for_a_different_install(self, client, seed):
        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        code = mint.json()["code"]
        verify = await client.post(f"{API}/pos-link/verify", json={"code": code})
        ref = verify.json()["registration_ref"]

        first = await client.post(f"{API}/pos-link/consume",
                                   json={"registration_ref": ref,
                                         "pos_install_id": "install-A"})
        assert first.status_code == 200, first.text

        second = await client.post(f"{API}/pos-link/consume",
                                    json={"registration_ref": ref,
                                          "pos_install_id": "install-B"})
        assert second.status_code == 400
        assert second.json()["detail"] == "Code not valid"

    @pytest.mark.asyncio
    async def test_consume_is_idempotent_for_the_same_install(self, client, seed):
        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        code = mint.json()["code"]
        verify = await client.post(f"{API}/pos-link/verify", json={"code": code})
        ref = verify.json()["registration_ref"]

        first = await client.post(f"{API}/pos-link/consume",
                                   json={"registration_ref": ref,
                                         "pos_install_id": "install-A"})
        assert first.status_code == 200, first.text

        second = await client.post(f"{API}/pos-link/consume",
                                    json={"registration_ref": ref,
                                          "pos_install_id": "install-A"})
        assert second.status_code == 200, second.text
        assert second.json()["outlet_id"] == first.json()["outlet_id"]

    @pytest.mark.asyncio
    async def test_bad_registration_ref_returns_generic_400(self, client, seed):
        r = await client.post(f"{API}/pos-link/consume",
                               json={"registration_ref": "not-a-real-ref",
                                     "pos_install_id": "install-A"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Code not valid"

    @pytest.mark.asyncio
    async def test_consume_stamps_outlet_pos_registered_at(self, client, seed, db):
        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        code = mint.json()["code"]
        verify = await client.post(f"{API}/pos-link/verify", json={"code": code})
        ref = verify.json()["registration_ref"]

        r = await client.post(f"{API}/pos-link/consume",
                               json={"registration_ref": ref,
                                     "pos_install_id": "install-A"})
        assert r.status_code == 200, r.text

        row = (await db.execute(text(
            "SELECT pos_registered_at FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})).scalar()
        assert row is not None


class TestFixedTestMode:
    """POS_REG_MODE=fixed-test: code is always "1234", reusable, TTL ignored.
    Separately refused outside NON_PRODUCTION_ENVS at startup -- see
    tests/test_api_pos_link_posture.py."""

    @pytest.mark.asyncio
    async def test_fixed_test_code_is_reusable_across_installs(self, client, seed, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "POS_REG_MODE", "fixed-test")

        mint = await client.post(f"{API}/owner/pos-registration-code",
                                  headers=seed["owner_auth"])
        assert mint.json()["code"] == "1234"

        for install in ("install-A", "install-B"):
            verify = await client.post(f"{API}/pos-link/verify", json={"code": "1234"})
            assert verify.status_code == 200, verify.text
            ref = verify.json()["registration_ref"]
            consume = await client.post(f"{API}/pos-link/consume",
                                         json={"registration_ref": ref,
                                               "pos_install_id": install})
            assert consume.status_code == 200, consume.text
