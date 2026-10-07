"""SQLAlchemy statement echo is opt-in, and defaults to OFF.

`create_async_engine(..., echo=True)` was hardcoded in core/database.py. echo
logs EVERY statement together with its bound parameters, so on Render the whole
query stream — customer phone numbers, pickup codes, token subjects — was
written into the platform log store, which has a different retention and access
model from the database itself. It also costs per-statement formatting on every
request.

The fix is a setting, which means two things have to stay true and neither is
visible by reading one file:

  1. the DEFAULT is False, so a deploy that sets nothing is quiet; and
  2. the engine actually READS the setting rather than a literal.

A test for (1) alone would still pass if someone re-hardcoded echo=True, and a
test for (2) alone would still pass if the default flipped to True. Both are
asserted here.
"""
import inspect
import re

import pytest

from app.core import database
from app.core.config import Settings, settings


def test_the_default_is_off():
    """Asserted on the FIELD DEFAULT, not on the live `settings` object.

    The live object reads .env, and a developer with SQL_ECHO=true set locally
    must not make this test pass or fail differently from CI. The declared
    default is the thing a fresh deploy inherits.
    """
    field = Settings.model_fields["SQL_ECHO"]
    assert field.default is False, (
        f"SQL_ECHO's declared default is {field.default!r}; a deploy that sets "
        "nothing would log every statement with its parameters")


def test_the_flag_is_a_bool_not_a_string():
    """'false' as a string is truthy, which would silently defeat the default.

    Pydantic coerces env values to the annotated type, so this pins the
    annotation that makes SQL_ECHO=false actually mean false.
    """
    assert Settings.model_fields["SQL_ECHO"].annotation is bool
    assert isinstance(settings.SQL_ECHO, bool)


def test_the_engine_reflects_the_setting():
    """The live engine's echo must equal the setting — not a literal.

    SQLAlchemy normalises echo to a bool (or the string 'debug') on the Engine,
    so this compares truthiness rather than identity.
    """
    assert bool(database.engine.echo) == bool(settings.SQL_ECHO), (
        f"engine.echo is {database.engine.echo!r} but SQL_ECHO is "
        f"{settings.SQL_ECHO!r} — the engine is not reading the setting")


def test_the_test_suite_itself_runs_quiet():
    """conftest does not set SQL_ECHO, so this run inherits the default.

    Doubles as the regression guard the other tests cannot give: if the default
    is ever flipped, or .env starts shipping SQL_ECHO=true, this fails and says
    why rather than quietly dumping every parameter into CI output.
    """
    assert settings.SQL_ECHO is False, (
        "this suite is running with statement echo ON, which writes bound "
        "parameters into the test log")
    assert not database.engine.echo


def test_echo_is_not_hardcoded_in_the_engine_call():
    """A literal `echo=True` would pass every assertion above except this one.

    The three tests above all compare the engine against the setting, so a
    re-hardcoded `echo=True` plus a flipped default would be self-consistent
    and invisible. This reads the source of the module that builds the engine
    and insists the argument is wired to the setting.
    """
    src = inspect.getsource(database)
    # Comments in this module legitimately mention the old `echo=True`, so the
    # scan is limited to the create_async_engine(...) call itself.
    call = re.search(r"create_async_engine\((.*?)\)", src, re.DOTALL)
    assert call, "create_async_engine call not found in core/database.py"
    args = call.group(1)
    assert "echo=settings.SQL_ECHO" in args.replace(" ", ""), (
        f"echo is not wired to the setting in the engine call: {args!r}")
    assert not re.search(r"echo\s*=\s*(True|False)\b", args), (
        f"echo is hardcoded in the engine call: {args!r}")


@pytest.mark.parametrize("raw, expected", [
    ("true", True), ("True", True), ("1", True),
    ("false", False), ("False", False), ("0", False),
])
def test_env_values_parse_the_way_an_operator_would_expect(raw, expected):
    """Set by hand in a Render dashboard field, so the spellings people
    actually type have to work — especially 'false', which as a bare string
    would be truthy."""
    assert Settings(SQL_ECHO=raw).SQL_ECHO is expected
