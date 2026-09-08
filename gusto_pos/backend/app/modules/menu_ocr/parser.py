"""Turn raw OCR text into candidate {name, price} pairs.

## BEST-EFFORT. NOT EXACT.
This is a heuristic over lines of text produced by an OCR pass over a
photograph of a printed menu. It WILL get things wrong: it will miss dishes,
invent splits, mis-read prices, and pick up headings and phone numbers. That is
accepted by design — nothing here writes to the menu. Every candidate is shown
to the owner, is editable, and reaches `menu_items` only when they tick it and
press Approve. The heuristic's job is to save typing, not to be right.

Kept as PURE FUNCTIONS over strings, deliberately separate from the OCR engine:
the engine needs a ~350 MB dependency and real image bytes, while the rules
below are where the actual judgement lives and are the part worth testing
exhaustively. The tests for this file import no OCR at all.

## The shape of the problem
A menu line usually reads `<dish name> .... <price>`, with the price last —
that is the layout convention the rules lean on. Everything else is noise
removal around that one observation.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# Currency amounts. Rupees are the target, but the symbol is optional because
# most menus print it once in a header and then just the digits.
#
#   250      250.00     ₹250     Rs. 250     Rs 1,250     INR 250/-
#
# The thousands separator is Indian-grouped or plain; both are stripped before
# float(). A leading `.` is not accepted, so an ellipsis dot-leader ("....250")
# cannot be read as a decimal point.
_PRICE = re.compile(
    r"""
    (?:(?P<sym>₹|Rs\.?|INR)\s*)?      # optional currency marker
    (?P<amount>
        \d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?   # 1,250  1,25,000  1,250.50
        |
        \d+(?:\.\d{1,2})?                     # 250    250.00
    )
    \s*(?:/-|/=)?                     # the common Indian "250/-" tail
    """,
    re.VERBOSE | re.IGNORECASE,
)

# A price sits at the END of the line, after the dish name. Anchored so a
# quantity inside the name ("2 pc") cannot be taken as the price.
_TRAILING_PRICE = re.compile(_PRICE.pattern + r"\s*$", re.VERBOSE | re.IGNORECASE)

# Dot leaders, dashes and pipes between name and price on a printed menu.
_LEADER = re.compile(r"[.•·\-–—_|:]{2,}\s*$")

# Section headings and boilerplate. Matched on the WHOLE line only, so a dish
# genuinely called "Veg Starter Platter" is not dropped.
_NOISE_LINES = {
    "menu", "our menu", "food menu", "menu card", "price list", "rate list",
    "starters", "starter", "appetizers", "appetiser", "appetisers",
    "mains", "main course", "main courses", "»main", "sides", "side dishes",
    "desserts", "dessert", "beverages", "drinks", "soft drinks", "hot drinks",
    "breads", "rice", "biryani", "curries", "soups", "salads", "combos",
    "veg", "non veg", "non-veg", "vegetarian", "non vegetarian",
    "gst extra", "taxes extra", "prices are in inr", "all prices in inr",
    "thank you", "visit again", "take away", "home delivery",
}

# Lines that are purely structural: a bare price, a bare number, a rule of
# dashes, a page marker.
_JUNK_LINE = re.compile(r"^[\s\.\-–—_=*|~•·]*$")

# Phone numbers and the like — long digit runs that are never a dish price.
_PHONE = re.compile(r"(?:\+?\d[\d\s\-]{8,}\d)")

# A plausible dish price. Outside this band it is almost certainly a phone
# number fragment, a year, a GST number or a street address, and admitting it
# would put obvious garbage in front of the owner.
MIN_PRICE = 1.0
MAX_PRICE = 100_000.0

# A dish name shorter than this is OCR debris ("A", "1x"). Longer than the max
# is a sentence — a description or an address — not a dish.
MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 120


def _to_float(amount: str) -> Optional[float]:
    try:
        return float(amount.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clean_name(raw: str) -> str:
    """Strip leader dots, bullets, item numbers and stray punctuation."""
    name = _LEADER.sub("", raw).strip()
    # Leading list markers: "1.", "12)", "-", "*", "•"
    name = re.sub(r"^\s*(?:\d{1,2}\s*[.)\]]|[-*•·])\s*", "", name)
    # Collapse the whitespace OCR sprays through wide-tracked headings.
    name = re.sub(r"\s{2,}", " ", name)
    # Trailing separators left behind once the price was removed.
    name = name.strip(" \t.-–—_:|,")
    return name.strip()


def _is_noise(line: str) -> bool:
    stripped = line.strip().lower().strip(" .:-–—_|")
    if not stripped:
        return True
    if stripped in _NOISE_LINES:
        return True
    # A heading in the middle of a menu is usually short and has no price;
    # that case is handled by the no-price branch in parse_lines, not here.
    return False


def parse_lines(lines: Iterable[str]) -> list[dict]:
    """Best-effort {name, price} pairs from OCR text lines.

    Rules, in order:

    1. Drop structural junk, known headings and lines carrying a phone number.
    2. Take the price from the END of the line. A line with no trailing price
       is not a dish row — it is a heading, a description, or a name whose
       price landed on the next line (see 3).
    3. If a line is JUST a price and the previous line was JUST a name, pair
       them. Two-column menus OCR that way often enough to be worth handling.
    4. Reject implausible prices and implausible names.

    Duplicates are collapsed on (lowercased name, price): the same dish read
    twice off two overlapping photos is one candidate, not two.
    """
    rows = [ln for ln in lines]
    out: list[dict] = []
    seen: set[tuple[str, float]] = set()
    pending_name: Optional[str] = None

    for raw in rows:
        line = (raw or "").strip()

        if _JUNK_LINE.match(line):
            pending_name = None
            continue

        # A phone number is never a menu row, and its digits would otherwise
        # be read as a price.
        if _PHONE.search(line):
            pending_name = None
            continue

        if _is_noise(line):
            pending_name = None
            continue

        match = _TRAILING_PRICE.search(line)

        if not match:
            # No price here. Could be the name half of a split row — remember
            # it, but only if it looks like a name rather than a sentence.
            candidate = _clean_name(line)
            pending_name = (
                candidate
                if MIN_NAME_LENGTH <= len(candidate) <= MAX_NAME_LENGTH
                else None
            )
            continue

        price = _to_float(match.group("amount"))
        name = _clean_name(line[: match.start()])

        # Rule 3: the line is a bare price; borrow the name above it.
        if not name and pending_name:
            name = pending_name

        pending_name = None

        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            continue
        if not (MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH):
            continue
        # A "name" that is only digits/punctuation is a table artefact.
        if not re.search(r"[A-Za-zऀ-ॿ]", name):
            continue

        key = (name.lower(), price)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "price": price})

    return out


def parse_text(text: str) -> list[dict]:
    """[parse_lines] over a single blob, split on newlines."""
    return parse_lines((text or "").splitlines())
