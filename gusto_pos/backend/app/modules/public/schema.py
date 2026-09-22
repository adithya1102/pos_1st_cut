"""Response schemas for the unauthenticated /public/* catalogue.

EVERY FIELD IS WRITTEN OUT BY HAND HERE. These models deliberately do NOT
inherit from, reuse, or `model_config`-copy `OutletRead`, `MenuItemResponse`,
or the carevo_customer `OutletOut`. That is the whole point of the file.

Reusing an existing model would mean this endpoint's public surface is decided
somewhere else, by someone adding a column to a schema they believe is
internal. `outlets.phone_number` arrived exactly that way in migration 009 —
additive, reasonable, and it would have appeared here for free. An explicit
field list cannot leak a column that nobody added to it.

WHAT IS EXCLUDED, and why each one is named rather than merely absent:

    phone_number            direct line to the owner; spammable at scale
    organization_id         internal tenancy graph, of no use to a caller
    geofence_radius_meters  operational tuning, reveals pickup mechanics
    verification_status     internal platform state
    upi_id                  payment handle
    image_url               not requested
    locality, deactivated_at, is_visible, created_at
    price rules             per-zone pricing (normal/ac) is commercial data;
                            only the single base price is published
    modifiers, tags, prep_time_minutes, short_code, station,
    base_prep_seconds, occupancy_seconds, hold_tolerance_seconds,
    is_batchable, image_url, id (menu item)

A test asserts the served keys equal the sets below exactly, so adding a column
to `outlets` or `menu_items` can never widen this response without a test going
red first.
"""

from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, Field


class PublicOutlet(BaseModel):
    """One outlet, as a stranger with no account may see it.

    EXACTLY these seven fields:

        id, name, city, latitude, longitude, opens_at, closes_at,
        open_status, open_reason

    `id` is included although it is not "about" the outlet: it is the argument
    to the menu endpoint, and without it this list is a dead end. It is an
    opaque UUID that already appears in customer-facing URLs.

    `name` is the API's name for the column `location_name`. Renamed at the
    boundary because "location_name" is an internal spelling, and a caller
    asking "what is this restaurant called" should not have to know it.
    """

    id: uuid.UUID
    name: str = Field(description="Public display name of the outlet.")
    city: str | None = Field(default=None, description="City, if recorded.")

    # DECIMAL in the DB; float over the wire. Precision is 8 and 8 decimal
    # places (~1mm), far beyond what a map pin needs.
    latitude: float | None = None
    longitude: float | None = None

    # Daily RECURRING time-of-day, not a date. NULL for either means no
    # schedule is on record, which the availability rules read as always open.
    opens_at: time | None = None
    closes_at: time | None = None

    # "open" | "closing_soon" | "closed" — computed by the same function that
    # gates real order acceptance, so this cannot drift from the truth.
    open_status: str
    open_reason: str | None = None


class PublicMenuItem(BaseModel):
    """One orderable item. EXACTLY four fields: name, price, is_veg, is_available.

    NO `description`. The `menu_items` table does not have such a column —
    not in the model, not in any migration, not in the live schema. It is not
    omitted here for safety; it does not exist to omit. See the module note in
    controller.py.

    `is_available` is published as-is rather than used to filter, matching what
    the customer app already does: a sold-out item is shown and marked, because
    a regular scanning for their usual dish cannot tell "sold out today" from
    "taken off the menu" from "wrong restaurant" when the row is simply gone.
    """

    name: str
    price: float = Field(description="Base price. Per-zone price rules are NOT published.")
    is_veg: bool
    is_available: bool


class PublicMenuCategory(BaseModel):
    """One menu section: its name, and the items in it.

    EXACTLY two fields. The category's own id is NOT published — nothing a
    public reader can do needs it, and the menu endpoint is addressed by
    outlet, never by category.
    """

    name: str = Field(description="Category display name, e.g. 'Mains'.")
    items: list[PublicMenuItem]


class PublicMenu(BaseModel):
    """The latest menu for one outlet: the outlet's id and name, and its
    categories, each holding its own items.

    Grouped rather than flat because a menu without its sections is a worse
    answer to "what do they serve" — a reader cannot tell a starter from a
    dessert. The per-item field list is UNCHANGED by the grouping: an item
    still carries exactly name, price, is_veg, is_available, and the category
    name lives on the category, not repeated onto every item.

    A category with no active items does not appear at all. `is_available`
    still does NOT filter, so a section whose every dish is sold out is
    present with its items flagged — only deletion removes a section.
    """

    outlet_id: uuid.UUID
    outlet_name: str
    categories: list[PublicMenuCategory]
