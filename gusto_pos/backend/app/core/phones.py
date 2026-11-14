"""Indian mobile number normalization — THE one definition (TASK 2).

The same rule ships in both Flutter apps (customer_app and owner_app each
carry lib/utils/in_mobile.dart); the three implementations are kept in step
by their test vectors, which are identical by construction.

Rule: strip everything that is not a digit, keep the LAST ten digits, and
accept the result only when it is exactly ten digits starting 6-9 (the TRAI
mobile number space). Everything else raises.

Canonical STORAGE form stays "+91" + the ten digits — the E.164 spelling
Firebase already writes — so nothing about the customers table changes.
Existing rows are NOT migrated: matching uses `in_mobile_variants` on the
lookup side instead, which covers every legacy spelling this codebase has
ever written (bare ten digits, 91-prefixed, E.164).
"""

import re

_DIGITS = re.compile(r"\D")


class PhoneValidationError(ValueError):
    """Raised when an input cannot be read as an Indian mobile number."""


def normalize_in_mobile(raw: str) -> str:
    """The ten subscriber digits of [raw], or PhoneValidationError.

    "919499956612", "+919499956612", "09499956612", "9499956612",
    "94999 56612" and "+91-94999-56612" all return "9499956612".
    """
    digits = _DIGITS.sub("", raw or "")
    if len(digits) > 10:
        # A garbled or doubled prefix corrupts the FRONT of the string,
        # never the subscriber number at the end.
        digits = digits[-10:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise PhoneValidationError(
            "Enter a 10-digit Indian mobile number (it starts with 6-9)."
        )
    return digits


def canonical_in_mobile(raw: str) -> str:
    """Canonical storage spelling: '+91' + the ten digits."""
    return "+91" + normalize_in_mobile(raw)


def in_mobile_variants(raw: str) -> list[str]:
    """Every spelling of [raw] that a legacy row might hold, canonical first.

    Raises PhoneValidationError for input that is not an Indian mobile
    number — callers that must stay tolerant of legacy non-mobile values
    catch it and fall back to exact matching.
    """
    ten = normalize_in_mobile(raw)
    return ["+91" + ten, ten, "91" + ten]
