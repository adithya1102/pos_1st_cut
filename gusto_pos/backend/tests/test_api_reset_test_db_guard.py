"""Task 4 (independent-verification fix) — the safety gate in
tests/reset_test_db.py must refuse a non-local host or a wrong database
name BEFORE any network I/O, never after.

NOTE: this test file does not exercise the live database at all (by
design — the whole point is proving the refusal happens before any
connection attempt), so it needs none of the ordinary `client`/`seed`/`db`
fixtures other files in this suite use.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reset_test_db  # noqa: E402


class _ConnectCalled(Exception):
    """Raised by the patched asyncpg.connect if it is ever reached — proves
    the guard did NOT stop the script before network I/O."""


@pytest.fixture(autouse=True)
def _forbid_any_connection(monkeypatch):
    async def _boom(*args, **kwargs):
        raise _ConnectCalled("asyncpg.connect was called — the guard did "
                             "not refuse before network I/O")
    monkeypatch.setattr(reset_test_db.asyncpg, "connect", _boom)


class TestAssertSafeTargetRefusesWithoutConnecting:
    @pytest.mark.parametrize("bad_host", [
        "10.0.0.5", "example.com", "0.0.0.0", "", "127.0.0.1.evil.com",
    ])
    def test_non_local_host_refused(self, bad_host):
        with pytest.raises(SystemExit, match="host"):
            reset_test_db.assert_safe_target(bad_host, "carevo_test")

    @pytest.mark.parametrize("bad_db", [
        "postgres", "carevo", "carevo_test2", "CAREVO_TEST", "", "gusto_pos",
    ])
    def test_non_carevo_test_database_refused(self, bad_db):
        with pytest.raises(SystemExit, match="database name"):
            reset_test_db.assert_safe_target("127.0.0.1", bad_db)

    def test_localhost_spelling_is_accepted(self):
        # Must not raise.
        reset_test_db.assert_safe_target("localhost", "carevo_test")

    def test_127_0_0_1_and_carevo_test_together_are_accepted(self):
        # Must not raise.
        reset_test_db.assert_safe_target("127.0.0.1", "carevo_test")

    def test_main_refuses_before_any_connect_call(self, monkeypatch):
        """End-to-end through main(): even if someone edits the module-level
        HOST/DB_NAME constants to something unsafe, main() must still call
        assert_safe_target as its very first action, before
        _drop_and_create_database ever opens a socket."""
        monkeypatch.setattr(reset_test_db, "HOST", "evil.example.com")
        import asyncio
        try:
            asyncio.run(reset_test_db.main())
            raised = None
        except BaseException as exc:
            raised = exc
        # Explicit type comparison, not pytest.raises: makes the failure
        # mode an assertion (comparing two type objects) rather than relying
        # on an exception-type mismatch to surface the problem.
        assert type(raised) is SystemExit, (
            f"expected SystemExit from the guard before any connection; "
            f"got {type(raised).__name__ if raised else None} instead "
            f"(a non-SystemExit here means network I/O was reached)")
