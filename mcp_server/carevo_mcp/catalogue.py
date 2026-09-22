"""HTTP client for the backend's public catalogue.

Talks ONLY to /api/v1/public/*. That restriction is the security boundary of
this whole server and it is enforced here, in one place: every request goes
through `_get()`, which joins onto `_PUBLIC_PREFIX` and cannot be pointed at
`/api/v1/customers/` or `/api/v1/admin/*` by a caller. There is no generic
"call the backend" helper for a future tool to reach for.

No credentials are sent, ever. Not "none configured" — none are read from the
environment, so a token cannot be picked up by accident from a shared host.
The endpoints are unauthenticated by design and the data is public catalogue
copy; if a future endpoint needs auth, it does not belong behind this client.

Unlike info.py's static literal, nothing here is shared mutable state: each
call parses a fresh JSON document into fresh objects, so there is no module
dict for one caller's mutation to reach. The copy discipline that info.py needs
is satisfied structurally here rather than by defensive copying.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

# Where the backend lives. Defaults to the deployed service so a stdio launch
# with no environment at all still works in Claude Desktop; override for local
# development against http://localhost:8000.
API_BASE = os.getenv("CAREVO_API_BASE", "https://gusto-pos-backend.onrender.com").rstrip("/")

_PUBLIC_PREFIX = "/api/v1/public"

# Render's free tier cold-starts, and a sleeping instance can take a while to
# answer the first request. Generous enough to survive that, bounded enough
# that a hung backend does not hang the MCP client indefinitely.
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)


class CatalogueError(RuntimeError):
    """A backend read failed. Message is safe to show a user."""


async def _get(path: str) -> Any:
    """GET `_PUBLIC_PREFIX + path` and return parsed JSON.

    Failures become CatalogueError with a plain-language message. The tool
    layer turns these into a returned error string rather than a protocol-level
    exception, because a model reading the result can act on "that outlet does
    not exist" but not on a traceback.
    """
    url = f"{API_BASE}{_PUBLIC_PREFIX}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as exc:
        raise CatalogueError(
            "The CareVo backend did not respond in time. It may be waking from "
            "idle — try once more in a few seconds."
        ) from exc
    except httpx.HTTPError as exc:
        raise CatalogueError(f"Could not reach the CareVo backend: {exc}") from exc

    if resp.status_code == 404:
        raise CatalogueError("No such outlet, or it is not publicly listed.")
    if resp.status_code == 429:
        raise CatalogueError(
            "Rate limited by the CareVo backend. Wait a little and retry."
        )
    if resp.status_code >= 400:
        raise CatalogueError(
            f"The CareVo backend returned {resp.status_code} for this request."
        )

    try:
        return resp.json()
    except ValueError as exc:
        raise CatalogueError("The CareVo backend returned a malformed response.") from exc


async def fetch_outlets() -> list[dict]:
    """Every publicly listed outlet."""
    data = await _get("/outlets")
    if not isinstance(data, list):
        raise CatalogueError("Expected a list of outlets from the backend.")
    return data


async def fetch_menu(outlet_id: str) -> dict:
    """The current public menu for one outlet, grouped by category.

    Shape: {outlet_id, outlet_name, categories: [{name, items: [...]}]}.
    """
    # Quoted so a caller cannot smuggle a path segment (`../../customers`) into
    # the URL. The backend also type-checks this as a UUID and 422s otherwise,
    # but the client should not be the thing relying on that.
    from urllib.parse import quote

    data = await _get(f"/outlets/{quote(str(outlet_id), safe='')}/menu")
    if not isinstance(data, dict):
        raise CatalogueError("Expected a menu object from the backend.")
    # Checked rather than assumed: this endpoint went from a flat `items` list
    # to grouped `categories`, and a client that silently tolerated either
    # would report an empty menu if the two ever drift apart again.
    if not isinstance(data.get("categories"), list):
        raise CatalogueError(
            "The CareVo backend returned a menu without categories — the "
            "client and the API may be out of step."
        )
    return data
