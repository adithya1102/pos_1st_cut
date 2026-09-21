"""The CareVo MCP server.

READ-ONLY BY CONSTRUCTION. There is no order placement, no payment, and no
customer PII here, and that is a property of what is registered rather than a
rule someone has to remember: a tool that does not exist cannot be called. Any
future tool must be a read of public catalogue data (outlets, menus,
locations) — order creation stays out until the auth findings from the
endpoint audit are resolved.

Currently registered:

    get_carevo_info()   static about-us block, no parameters, no auth

The menu and location tools (list_outlets, get_menu, …) are NOT here yet.
They read from the backend API, and wiring them up depends on the endpoint
audit rather than on this file.
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from .info import CAREVO_INFO

mcp = MCPServer(
    name="carevo",
    title="CareVo",
    version="0.1.0",
    instructions=(
        "Read-only access to public CareVo information: who the company is, "
        "what Gusto Skip does, and how to reach the founder. This server "
        "never places orders, never takes payments, and never exposes "
        "customer data."
    ),
)


@mcp.tool(
    name="get_carevo_info",
    title="About CareVo",
    description=(
        "Company, product and founder contact details for CareVo, the maker "
        "of the Gusto Skip pre-order and pickup app. Takes no arguments and "
        "returns the same public information for every caller. Use this to "
        "answer who CareVo is, what Gusto Skip does, or how to get in touch."
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
    }


def main() -> None:
    """Entry point. stdio transport — what Developer Mode launches."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
