"""Fail-closed POS-link posture: POS_REG_MODE=fixed-test (every registration
ID is the literal "1234", reusable, no expiry) must never be reachable in
production.

Mirrors test_api_auth_posture_fail_closed.py's matrix exactly — same
NON_PRODUCTION_ENVS convention, same "test" literal marker.
"""
from __future__ import annotations

import pytest

from app.core.config import (
    NON_PRODUCTION_ENVS,
    PosLinkConfigError,
    settings,
    validate_pos_link_startup_posture,
)

ENV_UNSET = object()
ENVS = (ENV_UNSET, "production", "development", "test")
MODES = ("random", "fixed-test", "FIXED-TEST", " fixed-test ")


def _expected_to_raise(env, mode: str) -> bool:
    resolved = "production" if env is ENV_UNSET else env
    if resolved in NON_PRODUCTION_ENVS or resolved == "test":
        return False
    return (mode or "").strip().lower() == "fixed-test"


CASES = [(env, mode) for env in ENVS for mode in MODES]


def _case_id(case):
    env, mode = case
    env_label = "unset" if env is ENV_UNSET else env
    return f"env={env_label},POS_REG_MODE={mode!r}"


class TestPosLinkPostureMatrix:
    @pytest.mark.parametrize("case", CASES, ids=[_case_id(c) for c in CASES])
    def test_matrix(self, case, monkeypatch):
        env, mode = case
        monkeypatch.setattr(settings, "POS_REG_MODE", mode)
        expected_raise = _expected_to_raise(env, mode)

        if env is ENV_UNSET:
            monkeypatch.delenv("APP_ENV", raising=False)
            call = lambda: validate_pos_link_startup_posture()
        else:
            call = lambda: validate_pos_link_startup_posture(env_name=env)

        if expected_raise:
            with pytest.raises(PosLinkConfigError) as exc:
                call()
            assert "POS_REG_MODE" in str(exc.value)
        else:
            call()  # must not raise


class TestPosLinkPostureDetails:
    def test_production_with_fixed_test_mode_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "POS_REG_MODE", "fixed-test")
        with pytest.raises(PosLinkConfigError) as exc:
            validate_pos_link_startup_posture(env_name="production")
        assert "POS_REG_MODE" in str(exc.value)
        assert "1234" in str(exc.value)  # names the shipped literal, not a secret

    def test_production_with_random_mode_starts(self, monkeypatch):
        monkeypatch.setattr(settings, "POS_REG_MODE", "random")
        validate_pos_link_startup_posture(env_name="production")

    def test_production_with_default_mode_starts(self, monkeypatch):
        # Default is "random" — fixed-test is an explicit opt-in only.
        monkeypatch.setattr(settings, "POS_REG_MODE", "random")
        validate_pos_link_startup_posture(env_name="production")

    def test_dev_envs_never_raise_even_with_fixed_test(self, monkeypatch):
        monkeypatch.setattr(settings, "POS_REG_MODE", "fixed-test")
        for env in NON_PRODUCTION_ENVS:
            validate_pos_link_startup_posture(env_name=env)

    def test_default_env_name_reads_the_live_app_env(self, monkeypatch):
        monkeypatch.setattr(settings, "POS_REG_MODE", "fixed-test")
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(PosLinkConfigError):
            validate_pos_link_startup_posture()
