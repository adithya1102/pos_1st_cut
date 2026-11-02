"""Task 3(b) — _estimate_prep_seconds (carevo_customer/service.py:1090) on a
NULL menu_items.prep_time_minutes.

LITERAL BEHAVIOUR, VERIFIED BEFORE ANY CODE CHANGE (none was made):
  The SQL itself already guards this —
      SELECT MAX(COALESCE(prep_time_minutes, :d)) FROM menu_items ...
  — so a NULL row is neither ignored (it is still one argument to MAX) nor
  read as zero (COALESCE substitutes DEFAULT_PREP_MINUTES_IF_UNKNOWN, 15
  minutes, before MAX ever sees it). The mission's conditional change
  ("if it can return zero or ignore the item, fall back to STATION_DEFAULTS")
  does not apply: neither precondition holds. This file pins the existing,
  already-safe fallback with a direct test, since none existed.

  Note the fallback used is DEFAULT_PREP_MINUTES_IF_UNKNOWN (a flat 15
  minutes), NOT prediction/service.py's STATION_DEFAULTS — a different table
  for a different purpose (post-order SLA timing, not the pre-order
  feasibility estimate this function produces). No station is known at order
  creation, so STATION_DEFAULTS has nothing to key on here.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.service import (
    DEFAULT_PREP_MINUTES_IF_UNKNOWN,
    CarevoService,
)


async def _set_prep_minutes(db, menu_item_id, minutes) -> None:
    await db.execute(text(
        "UPDATE menu_items SET prep_time_minutes = :m WHERE id = :i"),
        {"m": minutes, "i": str(menu_item_id)})
    await db.commit()


@pytest.mark.asyncio
class TestEstimatePrepSecondsNullFallback:
    async def test_null_prep_time_falls_back_to_default_not_zero(
            self, db, seed):
        await _set_prep_minutes(db, seed["menu_item_id"], None)
        items = [SimpleNamespace(menu_item_id=seed["menu_item_id"])]

        result = await CarevoService._estimate_prep_seconds(db, items)

        assert result == DEFAULT_PREP_MINUTES_IF_UNKNOWN * 60
        assert result != 0, "a NULL prep_time_minutes must not estimate zero prep time"

    async def test_null_item_is_not_dropped_from_the_slowest_of_calculation(
            self, db, seed):
        """A ticket with one FAST known item (5 min) and one NULL-timed item
        must take the NULL item's 15-minute default as the slowest-of-ticket
        answer — not silently exclude it and report the known item's 5
        minutes instead, which is exactly what 'ignoring the item' would
        look like."""
        second_item_id = uuid.uuid4()
        category_id = await db.scalar(text(
            "SELECT category_id FROM menu_items WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.execute(text("""
            INSERT INTO menu_items (id, category_id, name, base_price, is_veg,
                                    is_active, is_available, prep_time_minutes,
                                    created_at)
            VALUES (:i, :c, 'Second Dish', 50, true, true, true, NULL, now())
        """), {"i": str(second_item_id), "c": str(category_id)})
        await _set_prep_minutes(db, seed["menu_item_id"], 5)  # 300s, well below default
        await db.commit()

        items = [SimpleNamespace(menu_item_id=seed["menu_item_id"]),
                 SimpleNamespace(menu_item_id=str(second_item_id))]

        result = await CarevoService._estimate_prep_seconds(db, items)

        assert result == DEFAULT_PREP_MINUTES_IF_UNKNOWN * 60, (
            "the NULL-timed item's default was not taken into the slowest-of "
            "calculation — it was ignored instead"
        )

    async def test_empty_item_list_still_returns_the_default_not_zero(self, db):
        result = await CarevoService._estimate_prep_seconds(db, [])
        assert result == DEFAULT_PREP_MINUTES_IF_UNKNOWN * 60
        assert result != 0
