"""Menu photo import: the parsing heuristic, the endpoint, and the boundary.

Three things are being held here.

**The heuristic is best-effort and must fail SAFE.** It is a regex-and-lines
guess over OCR output. It is allowed to miss dishes. It is NOT allowed to put
obvious garbage — phone numbers, headings, prices with no dish — in front of the
owner, because a review screen full of junk is worse than an empty one.

**Nothing is created by OCR.** The endpoint returns suggestions and writes
nothing. The only path into `menu_items` is the ordinary POST /pos/menu-items,
and `TestOnlyApprovedItemsReachTheMenu` asserts exactly that.

**The dependency stays optional.** Most tests here stub the recognizer, so the
suite runs on a machine with no rapidocr installed — which is the state
requirements.txt ships in. The one test that exercises the real engine skips
itself when the package is absent.
"""
import io

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.menu_ocr import service as ocr
from app.modules.menu_ocr.parser import parse_lines, parse_text

API = "/api/v1"

# No module-level `pytest.mark.asyncio` here, unlike the older suites: pytest.ini
# sets asyncio_mode=auto, so async tests are collected anyway, and marking the
# module would tag the SYNC parser tests below too — 24 warnings about a mark on
# a non-async function.


# =============================================================================
# The heuristic, on realistic mess. Pure functions — no OCR, no DB, no app.
# =============================================================================
class TestTheParsingHeuristic:
    def test_a_plain_printed_menu(self):
        got = parse_text(
            "OUR MENU\n"
            "STARTERS\n"
            "Masala Dosa .......... 120\n"
            "Paneer Tikka ......... 260\n"
            "Filter Coffee ........ 40\n"
        )
        assert got == [
            {"name": "Masala Dosa", "price": 120.0},
            {"name": "Paneer Tikka", "price": 260.0},
            {"name": "Filter Coffee", "price": 40.0},
        ]

    @pytest.mark.parametrize("line,price", [
        ("Masala Dosa Rs. 120", 120.0),
        ("Masala Dosa Rs 120", 120.0),
        ("Masala Dosa ₹120", 120.0),
        ("Masala Dosa INR 120", 120.0),
        ("Masala Dosa 120/-", 120.0),
        ("Masala Dosa 120.00", 120.0),
        ("Masala Dosa 120.50", 120.5),
        ("Masala Dosa 1,250", 1250.0),
    ])
    def test_the_price_formats_a_real_menu_uses(self, line, price):
        got = parse_text(line)
        assert got == [{"name": "Masala Dosa", "price": price}]

    def test_a_number_in_the_dish_name_is_not_the_price(self):
        """'Chicken 65' is a dish, not a price. The price is the LAST number on
        the line, which is why the pattern is anchored to the end."""
        assert parse_text("Chicken 65 .... 320") == [
            {"name": "Chicken 65", "price": 320.0}
        ]
        assert parse_text("2 pc Chicken Roll 180") == [
            {"name": "2 pc Chicken Roll", "price": 180.0}
        ]

    def test_section_headings_are_dropped(self):
        got = parse_text(
            "MENU\nSTARTERS\nMains\nDesserts\nBeverages\n"
            "Gulab Jamun 90\n"
        )
        assert got == [{"name": "Gulab Jamun", "price": 90.0}]

    def test_a_phone_number_is_not_a_dish(self):
        """Its digits would otherwise parse as a price on a line that has a
        perfectly plausible 'name' in front of them."""
        got = parse_text(
            "Idli Sambar 60\n"
            "Phone: 080 4567 8910\n"
            "Call us on +91 98765 43210\n"
        )
        assert got == [{"name": "Idli Sambar", "price": 60.0}]

    def test_a_two_column_split_is_rejoined(self):
        """Photographed two-column menus OCR the name and the price onto
        separate lines often enough to be worth handling."""
        got = parse_text("Butter Naan\n45\nGarlic Naan\n55\n")
        assert got == [
            {"name": "Butter Naan", "price": 45.0},
            {"name": "Garlic Naan", "price": 55.0},
        ]

    def test_a_bare_price_with_no_name_above_it_is_dropped(self):
        assert parse_text("STARTERS\n120\n") == []

    def test_list_numbering_and_bullets_are_stripped(self):
        got = parse_text("1. Masala Dosa 120\n2) Idli 60\n- Vada 50\n")
        assert [c["name"] for c in got] == ["Masala Dosa", "Idli", "Vada"]

    def test_the_same_dish_photographed_twice_is_one_candidate(self):
        """Overlapping photos of one menu are the normal case at 10 images."""
        got = parse_text("Masala Dosa 120\nMasala Dosa 120\n")
        assert got == [{"name": "Masala Dosa", "price": 120.0}]

    def test_the_same_name_at_two_prices_is_two_candidates(self):
        """Half / full portions are genuinely two items, not a duplicate."""
        got = parse_text("Biryani 180\nBiryani 320\n")
        assert len(got) == 2

    def test_implausible_prices_are_rejected(self):
        got = parse_text(
            "Dosa 0\n"                      # free is a mis-read
            "Weird Item 999999\n"           # a GST number or an address
            "Real Dish 150\n"
        )
        assert got == [{"name": "Real Dish", "price": 150.0}]

    def test_rules_and_blank_lines_are_ignored(self):
        got = parse_text("-----------\n\n   \n=======\nDosa 120\n....\n")
        assert got == [{"name": "Dosa", "price": 120.0}]

    def test_a_name_that_is_only_punctuation_is_dropped(self):
        assert parse_text("... 120\n|| 90\n") == []

    def test_a_description_line_does_not_become_a_dish(self):
        """A sentence with no trailing price is a description; it must not be
        paired with the price on the row after it either."""
        got = parse_text(
            "Paneer Tikka 260\n"
            "Served with mint chutney and onion rings\n"
            "Dal Makhani 190\n"
        )
        assert got == [
            {"name": "Paneer Tikka", "price": 260.0},
            {"name": "Dal Makhani", "price": 190.0},
        ]

    def test_a_realistically_messy_page(self):
        """Everything at once, the way one photo actually comes back."""
        got = parse_text(
            "*** ANAND BHAVAN ***\n"
            "PRICE LIST\n"
            "\n"
            "STARTERS\n"
            "1. Gobi Manchurian ......... Rs. 180\n"
            "2. Chicken 65 .............. 320.50\n"
            "   Served hot with lemon\n"
            "\n"
            "MAIN COURSE\n"
            "Veg Biryani\n"
            "240/-\n"
            "Paneer Butter Masala ....... ₹ 1,250\n"
            "-----------------------------\n"
            "GST extra\n"
            "Phone: 080 4567 8910\n"
        )
        assert got == [
            {"name": "Gobi Manchurian", "price": 180.0},
            {"name": "Chicken 65", "price": 320.5},
            {"name": "Veg Biryani", "price": 240.0},
            {"name": "Paneer Butter Masala", "price": 1250.0},
        ]

    def test_empty_input_is_an_empty_list_not_a_crash(self):
        assert parse_text("") == []
        assert parse_lines([]) == []


# =============================================================================
# The endpoint. The recognizer is stubbed so the suite needs no rapidocr.
# =============================================================================
def _png(width=40, height=20) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def ocr_on(monkeypatch):
    """Enable OCR and replace the recognizer with scripted text.

    `_ocr_image_blocking` is what gets stubbed — everything above it (the flag
    check, the caps, the to_thread hop, the parse) stays real.
    """
    monkeypatch.setattr(settings, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)

    pages = {"lines": ["Masala Dosa 120", "Paneer Tikka 260"]}

    def _fake(data: bytes) -> list[str]:
        return list(pages["lines"])

    monkeypatch.setattr(ocr, "_ocr_image_blocking", _fake)
    return pages


class TestTheEndpoint:
    async def test_it_returns_candidates(self, client, seed, ocr_on):
        r = await client.post(
            f"{API}/pos/menu-import/ocr",
            headers=seed["owner_auth"],
            files=[("images", ("menu.png", _png(), "image/png"))],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["candidates"] == [
            {"name": "Masala Dosa", "price": 120.0},
            {"name": "Paneer Tikka", "price": 260.0},
        ]
        assert body["best_effort"] is True, "the app must never present these as facts"
        assert body["images_received"] == 1
        assert body["images_read"] == 1

    async def test_ten_images_are_accepted(self, client, seed, ocr_on):
        files = [("images", (f"m{i}.png", _png(), "image/png")) for i in range(10)]
        r = await client.post(f"{API}/pos/menu-import/ocr",
                              headers=seed["owner_auth"], files=files)
        assert r.status_code == 200, r.text
        assert r.json()["images_received"] == 10
        # Ten photos of one menu overlap heavily; dedup is what keeps the
        # review screen readable.
        assert r.json()["candidates"] == [
            {"name": "Masala Dosa", "price": 120.0},
            {"name": "Paneer Tikka", "price": 260.0},
        ]

    async def test_an_eleventh_image_is_refused(self, client, seed, ocr_on):
        files = [("images", (f"m{i}.png", _png(), "image/png")) for i in range(11)]
        r = await client.post(f"{API}/pos/menu-import/ocr",
                              headers=seed["owner_auth"], files=files)
        assert r.status_code == 422
        assert "10" in str(r.json())

    async def test_an_unreadable_photo_does_not_lose_the_others(
        self, client, seed, ocr_on, monkeypatch
    ):
        """One blurry photo out of three must not fail the batch."""
        calls = {"n": 0}

        def _flaky(data: bytes) -> list[str]:
            calls["n"] += 1
            return [] if calls["n"] == 2 else ["Idli Sambar 60"]

        monkeypatch.setattr(ocr, "_ocr_image_blocking", _flaky)
        files = [("images", (f"m{i}.png", _png(), "image/png")) for i in range(3)]
        r = await client.post(f"{API}/pos/menu-import/ocr",
                              headers=seed["owner_auth"], files=files)

        assert r.status_code == 200, r.text
        assert r.json()["images_read"] == 2, "the app can explain the short list"
        assert r.json()["images_received"] == 3
        assert r.json()["candidates"] == [{"name": "Idli Sambar", "price": 60.0}]

    async def test_a_non_image_is_refused(self, client, seed, ocr_on):
        r = await client.post(
            f"{API}/pos/menu-import/ocr",
            headers=seed["owner_auth"],
            files=[("images", ("menu.pdf", b"%PDF-1.4", "application/pdf"))],
        )
        assert r.status_code == 422

    async def test_it_needs_a_staff_token(self, client, ocr_on):
        r = await client.post(
            f"{API}/pos/menu-import/ocr",
            files=[("images", ("m.png", _png(), "image/png"))],
        )
        assert r.status_code in (401, 403)


class TestTheDependencyStaysOptional:
    async def test_it_is_503_when_ocr_is_off(self, client, seed, monkeypatch):
        """The state requirements.txt actually ships in. The route must mount
        and answer politely, not fail to import."""
        monkeypatch.setattr(ocr, "ocr_available", lambda: False)
        r = await client.post(
            f"{API}/pos/menu-import/ocr",
            headers=seed["owner_auth"],
            files=[("images", ("m.png", _png(), "image/png"))],
        )
        assert r.status_code == 503

    async def test_status_reports_the_deploys_capability(
        self, client, seed, monkeypatch
    ):
        """The app asks this before offering the button, so a deploy without
        the package shows manual entry instead of a button that only 503s."""
        monkeypatch.setattr(ocr, "ocr_available", lambda: False)
        off = await client.get(f"{API}/pos/menu-import/status",
                               headers=seed["owner_auth"])
        assert off.status_code == 200
        assert off.json()["enabled"] is False
        assert off.json()["max_images"] == 10

        monkeypatch.setattr(ocr, "ocr_available", lambda: True)
        on = await client.get(f"{API}/pos/menu-import/status",
                              headers=seed["owner_auth"])
        assert on.json()["enabled"] is True

    def test_ocr_available_needs_both_the_flag_and_the_package(self, monkeypatch):
        monkeypatch.setattr(settings, "OCR_ENABLED", False)
        assert ocr.ocr_available() is False


class TestOnlyApprovedItemsReachTheMenu:
    async def test_ocr_creates_nothing(self, client, seed, db, ocr_on):
        """The whole safety property of this feature."""
        before = await db.scalar(text("""
            SELECT count(*) FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE m.outlet_id = :o
        """), {"o": seed["outlet_id"]})

        r = await client.post(f"{API}/pos/menu-import/ocr",
                              headers=seed["owner_auth"],
                              files=[("images", ("m.png", _png(), "image/png"))])
        assert r.status_code == 200
        assert len(r.json()["candidates"]) == 2

        after = await db.scalar(text("""
            SELECT count(*) FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE m.outlet_id = :o
        """), {"o": seed["outlet_id"]})
        assert after == before, "OCR must never write to the menu"

    async def test_an_approved_candidate_goes_through_the_ordinary_path(
        self, client, seed, ocr_on
    ):
        """Approval reuses POST /pos/menu-items — there is no second creation
        route to keep in step with ownership scoping and category checks."""
        r = await client.post(f"{API}/pos/menu-import/ocr",
                              headers=seed["owner_auth"],
                              files=[("images", ("m.png", _png(), "image/png"))])
        candidates = r.json()["candidates"]

        cats = await client.get(f"{API}/pos/categories", headers=seed["owner_auth"])
        category_id = cats.json()[0]["id"]

        # Only the FIRST candidate is approved; the second is rejected.
        approved = candidates[0]
        created = await client.post(f"{API}/pos/menu-items",
                                    headers=seed["owner_auth"], json={
                                        "name": approved["name"],
                                        "base_price": approved["price"],
                                        "category_id": category_id,
                                        "is_veg": True,
                                    })
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "Masala Dosa"
        assert created.json()["base_price"] == 120.0

        listed = await client.get(f"{API}/pos/menu-items", headers=seed["owner_auth"])
        names = {i["name"] for i in listed.json()}
        assert "Masala Dosa" in names
        assert "Paneer Tikka" not in names, "a rejected candidate must not exist"


class TestTheRealEngine:
    """Exercises rapidocr itself. Skips where the package is not installed,
    which is the default state of requirements.txt."""

    async def test_a_rendered_menu_is_read_end_to_end(self, client, seed, monkeypatch):
        pytest.importorskip("rapidocr_onnxruntime")
        from PIL import Image, ImageDraw, ImageFont

        monkeypatch.setattr(settings, "OCR_ENABLED", True)

        def _font(size):
            for path in (r"C:\Windows\Fonts\arial.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
            return ImageFont.load_default()

        img = Image.new("RGB", (900, 460), "white")
        draw = ImageDraw.Draw(img)
        font = _font(34)
        draw.text((330, 30), "OUR MENU", font=_font(46), fill="black")
        rows = [("Masala Dosa", "Rs. 120"), ("Paneer Tikka", "260"),
                ("Chicken 65", "320.50"), ("Filter Coffee", "40/-")]
        y = 130
        for name, price in rows:
            draw.text((60, y), name, font=font, fill="black")
            draw.text((640, y), price, font=font, fill="black")
            y += 70

        buf = io.BytesIO()
        img.save(buf, "PNG")

        r = await client.post(
            f"{API}/pos/menu-import/ocr",
            headers=seed["owner_auth"],
            files=[("images", ("menu.png", buf.getvalue(), "image/png"))],
        )
        assert r.status_code == 200, r.text
        got = {c["name"]: c["price"] for c in r.json()["candidates"]}

        # Exact values, not a fuzzy count: this is the test that would catch
        # the span-regrouping breaking and every name losing its price.
        assert got.get("Masala Dosa") == 120.0
        assert got.get("Paneer Tikka") == 260.0
        assert got.get("Chicken 65") == 320.5, "a number in the name survives"
        assert got.get("Filter Coffee") == 40.0
        assert "OUR MENU" not in got, "the heading is not a dish"
