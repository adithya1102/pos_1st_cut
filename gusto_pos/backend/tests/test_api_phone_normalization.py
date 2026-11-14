"""TASK 2 — one Indian-mobile normalization rule, applied at the borders.

The helper (app/core/phones.py) is pure; its vectors here are the contract
shared verbatim with the two Flutter apps' lib/utils/in_mobile.dart.

The behavioural half: the stub OTP flow must MATCH legacy spellings of the
same number instead of creating a duplicate customer, and must STORE the
canonical "+91" form — while leaving behaviour for values the helper cannot
read (legacy test fixtures, garbage) exactly as it was (rule 8: an installed
app keeps working).
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.phones import (
    PhoneValidationError,
    canonical_in_mobile,
    in_mobile_variants,
    normalize_in_mobile,
)

API = "/api/v1"

GOOD = [
    "919499956612",
    "+919499956612",
    "09499956612",
    "9499956612",
    "94999 56612",
    "+91-94999-56612",
]
BAD = ["12345", "", "0000000000", "5499956612"]


class TestHelperVectors:
    def test_every_good_spelling_gives_the_same_ten_digits(self):
        for raw in GOOD:
            assert normalize_in_mobile(raw) == "9499956612", raw

    def test_bad_inputs_raise(self):
        for raw in BAD:
            with pytest.raises(PhoneValidationError):
                normalize_in_mobile(raw)

    def test_canonical_is_plus91_plus_ten(self):
        assert canonical_in_mobile("09499956612") == "+919499956612"

    def test_variants_cover_every_legacy_spelling(self):
        assert in_mobile_variants("94999 56612") == [
            "+919499956612", "9499956612", "919499956612",
        ]


@pytest.mark.asyncio
class TestOtpFlowUsesTheHelper:
    async def _verify(self, client, phone):
        r = await client.post(f"{API}/customer/auth/verify-otp",
                              json={"phone_number": phone, "otp": "000000"})
        assert r.status_code == 200, r.text
        return r.json()

    async def test_legacy_bare_row_is_matched_not_duplicated(self, client, db):
        """A pre-existing row holding the bare ten digits must be REUSED when
        the same number arrives in any other spelling, and upgraded to the
        canonical '+91' form — exactly what the Firebase path already does."""
        ten = "9499" + str(uuid.uuid4().int % 1000000).zfill(6)
        legacy_id = uuid.uuid4()
        await db.execute(text(
            "INSERT INTO customers (id, phone_number, points_balance, created_at) "
            "VALUES (:i, :p, 0, now())"), {"i": str(legacy_id), "p": ten})
        await db.commit()

        body = await self._verify(client, f"+91-{ten[:5]}-{ten[5:]}")
        assert body["customer"]["id"] == str(legacy_id), (
            "the legacy row must be matched, not a duplicate created")

        stored = await db.scalar(text(
            "SELECT phone_number FROM customers WHERE id = :i"),
            {"i": str(legacy_id)})
        assert stored == f"+91{ten}", "storage must be canonical +91 form"

    async def test_fresh_number_is_stored_canonically(self, client, db):
        ten = "9788" + str(uuid.uuid4().int % 1000000).zfill(6)
        body = await self._verify(client, f"0{ten}")
        stored = await db.scalar(text(
            "SELECT phone_number FROM customers WHERE id = :i"),
            {"i": body["customer"]["id"]})
        assert stored == f"+91{ten}"

    async def test_unreadable_value_keeps_legacy_behaviour(self, client, db):
        """Rule 8: a value the helper cannot read (legacy fixtures, odd test
        data) must flow through exactly as before — stored verbatim, matched
        exactly — rather than being rejected."""
        raw = f"+9199{uuid.uuid4().hex[:8]}"  # hex letters: not a mobile
        body = await self._verify(client, raw)
        stored = await db.scalar(text(
            "SELECT phone_number FROM customers WHERE id = :i"),
            {"i": body["customer"]["id"]})
        assert stored == raw
        # And the same raw spelling maps back to the same row.
        again = await self._verify(client, raw)
        assert again["customer"]["id"] == body["customer"]["id"]
