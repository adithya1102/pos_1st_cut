"""The CareVo MCP server.

READ-ONLY BY CONSTRUCTION. There is no order placement, no payment, and no
customer PII here, and that is a property of what is registered rather than a
rule someone has to remember: a tool that does not exist cannot be called.

Currently registered:

    get_carevo_info()       static about-us block, no parameters, no auth
    list_outlets()          public outlets: name, city, coords, hours, open state
    get_menu(outlet_id)     public menu: item name, price, veg flag, availability

The two catalogue tools read `/api/v1/public/*` on the backend — a router that
is unauthenticated BY DESIGN and whose response models name every field they
publish. This server cannot reach any other backend route: see catalogue.py,
where the public prefix is the only path that can be constructed.

Order creation stays out. It is not blocked by a flag here; it is simply not
written, and the enforcement test asserts it never appears.

TRANSPORTS. Both are supported from one definition of the tools:

    stdio            what Claude Desktop launches (default)
    streamable-http  a persistent web service, for remote HTTPS deployment

Selected by CAREVO_MCP_TRANSPORT, or --transport on the command line. Nothing
about a tool changes between the two; only how bytes move.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .catalogue import CatalogueError, fetch_menu, fetch_outlets
from .info import CAREVO_INFO

mcp = MCPServer(
    name="carevo",
    title="CareVo",
    version="0.2.0",
    instructions=(
        "Read-only access to public CareVo information: who the company is, "
        "what Gusto Skip does, how to reach the founder, which outlets exist "
        "and what is on their menus. This server never places orders, never "
        "takes payments, and never exposes customer data."
    ),
)


@mcp.tool(
    name="get_carevo_info",
    title="About CareVo",
    description=(
        "Company, product, founder contact details and official links for "
        "CareVo, the maker of the Gusto Skip pre-order and pickup app. Takes "
        "no arguments and returns the same public information for every "
        "caller. Use this to answer who CareVo is, what Gusto Skip does, how "
        "to get in touch, or where to find the website or the app. A link "
        "carrying a `status` field is not live yet — report what that field "
        "says instead of offering the URL."
    ),
)
def get_carevo_info() -> dict[str, Any]:
    """Return the static CareVo about-us block.

    A copy, not the module-level dict itself: handing out the live object
    would let one caller's mutation become every later caller's response.
    """
    return {
        "company": dict(CAREVO_INFO["company"]),
        "product": dict(CAREVO_INFO["product"]),
        "founder": dict(CAREVO_INFO["founder"]),
        # One level deeper than the others: each link is itself a dict, so a
        # plain dict() would copy the outer mapping and hand out the very same
        # inner objects — a caller editing links["company"]["url"] would edit
        # the module literal, for every later caller. tests/test_client.py
        # mutates a nested url specifically to keep this honest.
        "links": {key: dict(link) for key, link in CAREVO_INFO["links"].items()},
    }


@mcp.tool(
    name="list_outlets",
    title="List CareVo outlets",
    description=(
        "Every publicly listed Gusto Skip outlet: its id, name, city, "
        "coordinates, daily opening and closing times, and whether it is open "
        "right now. Takes no arguments. Use the returned `id` with get_menu. "
        "`open_status` is one of open / closing_soon / closed, and when it is "
        "not open, `open_reason` explains why in words meant for a customer. "
        "Null opening and closing times mean the outlet has no schedule on "
        "record and is treated as always open."
    ),
)
async def list_outlets() -> dict[str, Any]:
    """Public outlet list, read live from the backend."""
    try:
        outlets = await fetch_outlets()
    except CatalogueError as exc:
        # Returned, not raised: a model can act on this sentence, and an
        # is_error protocol result would give it only a failure to report.
        return {"error": str(exc), "outlets": []}
    return {"count": len(outlets), "outlets": outlets}


@mcp.tool(
    name="get_menu",
    title="Get an outlet's menu",
    description=(
        "The current menu for one Gusto Skip outlet, by outlet id (get ids "
        "from list_outlets). Items are grouped into categories: each category "
        "has a name and its own items, and each item has a name, price in "
        "rupees, whether it is vegetarian, and whether it is available right "
        "now. Present the categories as menu sections rather than flattening "
        "them. Items with `is_available` false are on the menu but sold out — "
        "say so rather than omitting them. Prices are the base price; this "
        "server does not expose per-zone pricing. An unknown or unlisted "
        "outlet returns an error message, not an empty menu."
    ),
)
async def get_menu(outlet_id: str) -> dict[str, Any]:
    """Public menu for one outlet, read live from the backend."""
    try:
        menu = await fetch_menu(outlet_id)
    except CatalogueError as exc:
        return {"error": str(exc), "categories": []}
    categories = menu.get("categories", [])
    return {
        "outlet_id": menu.get("outlet_id"),
        "outlet_name": menu.get("outlet_name"),
        "category_count": len(categories),
        # Total across all sections, so a reader does not have to sum them to
        # answer "how many dishes do they have".
        "item_count": sum(len(c.get("items", [])) for c in categories),
        "categories": categories,
    }


def main() -> None:
    """Entry point for both transports.

    stdio is the default because that is what Claude Desktop spawns and it
    must keep working untouched. streamable-http is opt-in, for running this
    as a persistent web service.

    PORT is read as a fallback for the host platform's convention (Render and
    most PaaS inject it), so a deployment needs no extra configuration beyond
    setting the transport.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="carevo-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("CAREVO_MCP_TRANSPORT", "stdio"),
        help="stdio for Claude Desktop (default); streamable-http to serve over HTTP.",
    )
    parser.add_argument("--host", default=os.getenv("CAREVO_MCP_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int,
        default=int(os.getenv("PORT", os.getenv("CAREVO_MCP_PORT", "8080"))),
    )
    parser.add_argument("--path", default=os.getenv("CAREVO_MCP_PATH", "/mcp"))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        transport_security=_transport_security(args.host),
    )


def _transport_security(host: str):
    """DNS-rebinding protection settings for the HTTP transport.

    This needs saying because the SDK's default is a trap for exactly the
    deployment we want. When `host` is a loopback address the SDK installs a
    localhost allow-list for you. When it is 0.0.0.0 — which is what binding on
    Render requires — it installs NOTHING, and the Host header stops being
    checked at all.

    So the allow-list is set explicitly from CAREVO_MCP_ALLOWED_HOSTS (comma
    separated, `example.com` or `example.com:*`). If that is unset we leave
    protection off rather than guessing a hostname, because an allow-list that
    does not contain the real domain rejects EVERY request with an opaque 421
    and looks exactly like a broken deployment. Off-and-documented beats
    on-and-silently-wrong; set the variable when deploying.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    raw = os.getenv("CAREVO_MCP_ALLOWED_HOSTS", "").strip()
    if not raw:
        return None

    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    origins = [f"https://{h}" for h in hosts if not h.startswith(("http://", "https://"))]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def http_app():
    """ASGI app for a external server (`uvicorn carevo_mcp.server:http_app --factory`).

    An alternative to `main() --transport streamable-http`, for hosts that want
    to own the server process and its worker model rather than have the SDK
    call uvicorn.run() itself.
    """
    return mcp.streamable_http_app(
        streamable_http_path=os.getenv("CAREVO_MCP_PATH", "/mcp"),
        host=os.getenv("CAREVO_MCP_HOST", "0.0.0.0"),
        transport_security=_transport_security(os.getenv("CAREVO_MCP_HOST", "0.0.0.0")),
    )


if __name__ == "__main__":
    main()
