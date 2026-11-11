"""Fail-closed customer-auth posture: the OTP stub must never be reachable
in production.

Before this file: OTP_STUB_MODE defaults to True and OTP_STUB_CODE to
"000000" (config.py), and POST /customer/auth/verify-otp is gated only by
CUSTOMER_AUTH_ENABLED (also defaulting True) — not by OTP_STUB_MODE. A
deploy that sets neither variable boots with the stub code reachable for
any phone number.

validate_auth_posture (app/core/config.py) now refuses to let the process
start in that shape outside a non-production environment. It mirrors
validate_gateway_startup_posture's environment convention exactly
(NON_PRODUCTION_ENVS, plus the literal "test" marker), so this matrix test
covers every combination of APP_ENV and the two flags.
"""
from __future__ import annotations

import pytest

from app.core.config import (
    AuthConfigError,
    NON_PRODUCTION_ENVS,
    settings,
    validate_auth_posture,
)


# APP_ENV values under test. "unset" means the APP_ENV env var itself is
# absent, so the function falls back to os.getenv("APP_ENV", "production")
# internally — exercised by NOT passing env_name and deleting the env var,
# exactly like validate_gateway_startup_posture's own
# test_default_env_name_reads_the_live_app_env.
ENV_UNSET = object()
ENVS = (ENV_UNSET, "production", "development", "test")

FLAG_COMBINATIONS = (
    (True, True),
    (True, False),
    (False, True),
    (False, False),
)


def _expected_to_raise(env, otp_stub_mode: bool, customer_auth_enabled: bool) -> bool:
    """Mirrors validate_auth_posture's own logic, independently restated so
    the test does not just re-run the implementation against itself."""
    resolved = "production" if env is ENV_UNSET else env
    if resolved in NON_PRODUCTION_ENVS or resolved == "test":
        return False
    return otp_stub_mode and customer_auth_enabled


CASES = [
    (env, otp_stub_mode, customer_auth_enabled)
    for env in ENVS
    for otp_stub_mode, customer_auth_enabled in FLAG_COMBINATIONS
]


def _case_id(case):
    env, otp_stub_mode, customer_auth_enabled = case
    env_label = "unset" if env is ENV_UNSET else env
    return f"env={env_label},OTP_STUB_MODE={otp_stub_mode},CUSTOMER_AUTH_ENABLED={customer_auth_enabled}"


class TestAuthPostureMatrix:
    @pytest.mark.parametrize("case", CASES, ids=[_case_id(c) for c in CASES])
    def test_matrix(self, case, monkeypatch):
        env, otp_stub_mode, customer_auth_enabled = case
        monkeypatch.setattr(settings, "OTP_STUB_MODE", otp_stub_mode)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", customer_auth_enabled)

        expected_raise = _expected_to_raise(env, otp_stub_mode, customer_auth_enabled)

        if env is ENV_UNSET:
            monkeypatch.delenv("APP_ENV", raising=False)
            call = lambda: validate_auth_posture()
        else:
            call = lambda: validate_auth_posture(env_name=env)

        if expected_raise:
            with pytest.raises(AuthConfigError) as exc:
                call()
            # Names both variables and the safe values; never a secret —
            # there is no secret value in play here, only two booleans.
            assert "OTP_STUB_MODE" in str(exc.value)
            assert "CUSTOMER_AUTH_ENABLED" in str(exc.value)
        else:
            call()  # must not raise


class TestAuthPostureDetails:
    def test_production_with_both_stub_flags_true_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "OTP_STUB_MODE", True)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", True)
        with pytest.raises(AuthConfigError) as exc:
            validate_auth_posture(env_name="production")
        msg = str(exc.value)
        assert "OTP_STUB_MODE" in msg
        assert "CUSTOMER_AUTH_ENABLED" in msg
        assert "false" in msg  # names the safe value

    def test_production_with_stub_mode_false_starts(self, monkeypatch):
        monkeypatch.setattr(settings, "OTP_STUB_MODE", False)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", True)
        validate_auth_posture(env_name="production")

    def test_production_with_customer_auth_disabled_starts(self, monkeypatch):
        monkeypatch.setattr(settings, "OTP_STUB_MODE", True)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", False)
        validate_auth_posture(env_name="production")

    def test_dev_envs_never_raise_even_with_both_flags_true(self, monkeypatch):
        monkeypatch.setattr(settings, "OTP_STUB_MODE", True)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", True)
        for env in NON_PRODUCTION_ENVS:
            validate_auth_posture(env_name=env)

    def test_default_env_name_reads_the_live_app_env(self, monkeypatch):
        monkeypatch.setattr(settings, "OTP_STUB_MODE", True)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", True)
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(AuthConfigError):
            validate_auth_posture()

    def test_never_leaks_a_value_only_names_variables(self, monkeypatch):
        monkeypatch.setattr(settings, "OTP_STUB_MODE", True)
        monkeypatch.setattr(settings, "CUSTOMER_AUTH_ENABLED", True)
        with pytest.raises(AuthConfigError) as exc:
            validate_auth_posture(env_name="production")
        # The message is built entirely from literal strings, never from an
        # f-string over a settings value — nothing secret could appear here
        # even by accident, but assert directly anyway.
        assert "000000" not in str(exc.value)
