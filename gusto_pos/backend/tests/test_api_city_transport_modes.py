"""Migration 030: the per-city transport mode grid.

Covers the three things that could silently go wrong:

  1. the data carry-across from 029 (train/metro must land intact, tram off)
  2. "absent means default" — the rule that replaces a backfill trigger, and
     which the admin read path and the customer read path must agree on
  3. the payload contract the app depends on, including that a mode the app
     has never heard of still arrives with its behaviour attached

Runs entirely on a TEMPORARY SCHEMA, not the live tables. The rest of this
suite talks to the shared database, which is why it is flaky when someone is
using the app; none of that applies here.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.service import CarevoService

MIGRATION = "gusto_pos/backend/migrations/030_city_transport_modes.sql"


def _read_migration() -> str:
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    return (root / "migrations" / "030_city_transport_modes.sql").read_text(
        encoding="utf-8")


async def _run_script(db, sql: str) -> None:
    """Execute a multi-statement SQL script.

    SQLAlchemy's asyncpg driver prepares every statement, and a prepared
    statement can hold exactly one command — so `text(migration)` fails with
    "cannot insert multiple commands into a prepared statement". Splitting on
    ';' is not an option either: the migration contains a `DO $$ ... $$` block
    whose body is full of semicolons.

    So this reaches the raw asyncpg connection, whose `execute()` uses the
    SIMPLE query protocol when given no parameters — which is exactly what a
    migration script needs, and what `psql -f` would do.
    """
    conn = await db.connection()
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(sql)


@pytest.fixture
async def grid(db):
    """A throwaway schema holding a 029-shaped `cities` table + migration 030.

    Building 029's shape by hand rather than reusing the real table is the
    point: it pins the BEFORE state the carry-across is supposed to read, so
    this test still means something after `has_train` is eventually dropped.
    """
    await _run_script(db, """
        DROP SCHEMA IF EXISTS t030 CASCADE;
        CREATE SCHEMA t030;
        SET search_path TO t030, public;
        CREATE TABLE cities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name varchar(80) NOT NULL,
            status varchar(12) NOT NULL DEFAULT 'active',
            city_type varchar(16) NOT NULL DEFAULT 'tier_2',
            has_train boolean NOT NULL DEFAULT false
        );
        -- Exactly prod's five rows, in prod's state when 030 was written.
        INSERT INTO cities (name, city_type, has_train) VALUES
            ('Chennai',   'metro',  true),
            ('Bengaluru', 'metro',  true),
            ('Kolkata',   'metro',  true),
            ('Kochi',     'metro',  true),
            ('Madurai',   'tier_2', false);
    """)
    await _run_script(db, _read_migration())
    yield db
    await _run_script(db, "DROP SCHEMA IF EXISTS t030 CASCADE; "
                          "SET search_path TO public;")


class TestCatalog:
    async def test_all_eight_modes_seeded(self, grid):
        rows = (await grid.execute(text(
            "SELECT code FROM transport_modes ORDER BY sort_order"))).fetchall()
        assert [r.code for r in rows] == [
            "walk", "bike", "car", "auto", "bus", "train", "metro", "tram"]

    async def test_declared_arrival_modes_are_exactly_the_rail_ones(self, grid):
        rows = (await grid.execute(text(
            "SELECT code FROM transport_modes WHERE uses_declared_arrival "
            "ORDER BY code"))).fetchall()
        assert [r.code for r in rows] == ["metro", "train", "tram"]

    async def test_road_modes_default_on_rail_modes_default_off(self, grid):
        rows = dict((r.code, r.default_enabled) for r in (await grid.execute(
            text("SELECT code, default_enabled FROM transport_modes"))).fetchall())
        assert all(rows[c] for c in ("walk", "bike", "car", "auto", "bus"))
        assert not any(rows[c] for c in ("train", "metro", "tram"))

    async def test_a_ninth_mode_needs_no_ddl(self, grid):
        """The extensibility claim, exercised rather than asserted."""
        await grid.execute(text(
            "INSERT INTO transport_modes "
            "(code, label, uses_declared_arrival, default_enabled, sort_order) "
            "VALUES ('ferry', 'Ferry', true, false, 90)"))
        n = await grid.scalar(text(
            "SELECT count(*) FROM transport_modes WHERE is_active"))
        assert n == 9
        # And it immediately participates in the read path with no other change.
        enabled = await grid.scalar(text("""
            SELECT COALESCE(ctm.enabled, m.default_enabled)
            FROM cities ci CROSS JOIN transport_modes m
            LEFT JOIN city_transport_modes ctm
                   ON ctm.city_id = ci.id AND ctm.mode_code = m.code
            WHERE m.code = 'ferry' AND lower(ci.name) = 'chennai'
        """))
        assert enabled is False


class TestCarryAcross:
    """029's data must land in the grid intact. Nothing lost, nothing invented."""

    async def test_row_count_is_cities_times_modes(self, grid):
        assert await grid.scalar(text(
            "SELECT count(*) FROM city_transport_modes")) == 5 * 8

    @pytest.mark.parametrize("city", ["Chennai", "Bengaluru", "Kolkata", "Kochi"])
    async def test_rail_cities_keep_train_and_metro(self, grid, city):
        row = (await grid.execute(text("""
            SELECT bool_or(m.mode_code='train' AND m.enabled) AS train,
                   bool_or(m.mode_code='metro' AND m.enabled) AS metro
            FROM cities ci JOIN city_transport_modes m ON m.city_id = ci.id
            WHERE ci.name = :n GROUP BY ci.id
        """), {"n": city})).first()
        assert row.train is True
        assert row.metro is True

    async def test_madurai_keeps_neither(self, grid):
        row = (await grid.execute(text("""
            SELECT bool_or(m.mode_code='train' AND m.enabled) AS train,
                   bool_or(m.mode_code='metro' AND m.enabled) AS metro
            FROM cities ci JOIN city_transport_modes m ON m.city_id = ci.id
            WHERE ci.name = 'Madurai' GROUP BY ci.id
        """))).first()
        assert row.train is False
        assert row.metro is False

    async def test_road_modes_on_everywhere(self, grid):
        off = await grid.scalar(text("""
            SELECT count(*) FROM city_transport_modes
            WHERE mode_code IN ('walk','bike','car','auto','bus') AND NOT enabled
        """))
        assert off == 0

    async def test_tram_starts_off_everywhere(self, grid):
        on = await grid.scalar(text(
            "SELECT count(*) FROM city_transport_modes "
            "WHERE mode_code = 'tram' AND enabled"))
        assert on == 0

    async def test_total_enabled_matches_the_029_snapshot(self, grid):
        # 25 road (5 cities x 5) + 4 train + 4 metro + 0 tram
        assert await grid.scalar(text(
            "SELECT count(*) FROM city_transport_modes WHERE enabled")) == 33

    async def test_rerunning_does_not_clobber_an_admin_choice(self, grid):
        """ON CONFLICT DO NOTHING: a re-run must not restore the 029 snapshot."""
        cid = await grid.scalar(text("SELECT id FROM cities WHERE name='Madurai'"))
        await grid.execute(text("""
            INSERT INTO city_transport_modes (city_id, mode_code, enabled)
            VALUES (:c, 'tram', true)
            ON CONFLICT (city_id, mode_code) DO UPDATE SET enabled = true
        """), {"c": cid})
        await _run_script(grid, _read_migration())
        still_on = await grid.scalar(text(
            "SELECT enabled FROM city_transport_modes "
            "WHERE city_id = :c AND mode_code = 'tram'"), {"c": cid})
        assert still_on is True


class TestAbsentMeansDefault:
    """The rule that replaces a backfill trigger."""

    async def test_a_city_with_no_rows_reads_as_the_catalog_default(self, grid):
        await grid.execute(text("INSERT INTO cities (name) VALUES ('Coimbatore')"))
        rows = (await grid.execute(text("""
            SELECT m.code, COALESCE(ctm.enabled, m.default_enabled) AS enabled
            FROM cities ci CROSS JOIN transport_modes m
            LEFT JOIN city_transport_modes ctm
                   ON ctm.city_id = ci.id AND ctm.mode_code = m.code
            WHERE ci.name = 'Coimbatore' ORDER BY m.sort_order
        """))).fetchall()
        got = {r.code: r.enabled for r in rows}
        assert got == {"walk": True, "bike": True, "car": True, "auto": True,
                       "bus": True, "train": False, "metro": False, "tram": False}


class TestCustomerPayload:
    """What `/customer/outlets` puts on the wire."""

    async def test_flags_are_derived_from_the_grid_not_city_type(self, grid):
        profiles = await CarevoService._city_transport_profiles(grid)
        chennai = profiles["chennai"]
        codes = {m["code"] for m in chennai["modes"]}
        assert "metro" in codes and "train" in codes
        assert "tram" not in codes

        flags = CarevoService._transport_flags(profiles, "Chennai")
        assert flags["has_metro"] is True
        assert flags["has_train"] is True
        assert [m["code"] for m in flags["transport_modes"]][:5] == [
            "walk", "bike", "car", "auto", "bus"]

    async def test_declared_arrival_travels_with_each_mode(self, grid):
        """Without this the app cannot handle a mode it has never heard of."""
        profiles = await CarevoService._city_transport_profiles(grid)
        by_code = {m["code"]: m for m in profiles["chennai"]["modes"]}
        assert by_code["metro"]["uses_declared_arrival"] is True
        assert by_code["train"]["uses_declared_arrival"] is True
        assert by_code["walk"]["uses_declared_arrival"] is False

    async def test_an_unknown_city_gets_nulls_not_falses(self, grid):
        """None means 'no answer' and lets the app fall back; False does not."""
        profiles = await CarevoService._city_transport_profiles(grid)
        flags = CarevoService._transport_flags(profiles, "Nowhere")
        assert flags["has_metro"] is None
        assert flags["has_train"] is None
        assert flags["transport_modes"] is None

    async def test_turning_tram_on_puts_it_in_the_payload(self, grid):
        cid = await grid.scalar(text("SELECT id FROM cities WHERE name='Kolkata'"))
        await grid.execute(text("""
            INSERT INTO city_transport_modes (city_id, mode_code, enabled)
            VALUES (:c, 'tram', true)
            ON CONFLICT (city_id, mode_code) DO UPDATE SET enabled = true
        """), {"c": cid})

        profiles = await CarevoService._city_transport_profiles(grid)
        flags = CarevoService._transport_flags(profiles, "Kolkata")
        tram = [m for m in flags["transport_modes"] if m["code"] == "tram"]
        assert len(tram) == 1
        assert tram[0]["uses_declared_arrival"] is True
        assert tram[0]["label"] == "Tram"
