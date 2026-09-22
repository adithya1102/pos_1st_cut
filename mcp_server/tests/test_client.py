"""End-to-end check: launch the server over stdio and drive it as a client.

Not a unit test of get_carevo_info() — calling the Python function directly
would prove nothing about REGISTRATION, which is the part that actually breaks
(a decorator that silently did not apply, a tool missing from list_tools, a
return value the protocol cannot serialise). This spawns the real server as a
subprocess, speaks MCP to it over stdio exactly as Developer Mode does, and
asserts on what comes back across that boundary.

Run:  python tests/test_client.py
"""

import asyncio
import json
import os
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent

EXPECTED_FOUNDER = {
    "name": "Adithya Narayanan C.",
    "known_as": "Adi",
    "title": "Founder",
    "email": "adithya@carevo.co.in",
    "whatsapp": "9499956612",
    "phone": "6374304790",
}

# Labels are asserted verbatim: they are the display text a caller shows a
# person, so a well-meaning reword is a user-visible change and should have to
# be made here too.
EXPECTED_LINKS = {
    "company": ("About our company", "https://carevo.co.in"),
    "product": ("Gusto Skip", "https://gustoskip.carevo.co.in"),
    "android_app": (
        "Get the app on Google Play",
        "https://play.google.com/store/apps/details?id=com.carevo.customer_app",
    ),
}

# Every tool that must exist. Asserted as an EXACT set further down, so a new
# tool appearing without a decision here fails just as loudly as one vanishing.
EXPECTED_TOOLS = {"get_carevo_info", "list_outlets", "get_menu"}

# Tools that must NEVER appear. The server is read-only by construction, but
# an assertion makes a future regression loud instead of quiet.
FORBIDDEN = (
    "create_order", "place_order", "pay", "checkout", "capture_payment",
    "get_customer", "list_customers", "get_user", "search_customers",
    "update_menu", "set_price", "delete_outlet", "refund",
)

# --- Stub backend -----------------------------------------------------------
# The catalogue tools are exercised against a local stub rather than the live
# service, for two reasons: the real backend needs a database, and a test that
# depends on production being up tests the network as much as the code.
#
# The stub speaks the SAME shape the real /api/v1/public/* endpoints serve —
# the field lists are copied from tests/test_api_public_catalogue.py, which pins
# them on the backend side. If the backend's shape drifts, that suite fails
# there; this one proves the MCP layer carries the shape through intact.
STUB_OUTLET_ID = "11111111-2222-4333-8444-555555555555"

STUB_OUTLETS = [
    {
        "id": STUB_OUTLET_ID,
        "name": "Stub Kitchen",
        "city": "Testville",
        "latitude": 12.97,
        "longitude": 77.59,
        "opens_at": "09:00:00",
        "closes_at": "22:00:00",
        "open_status": "open",
        "open_reason": None,
    }
]

# Two categories, so the round-trip proves items stay under the RIGHT section
# rather than merely surviving as a flat pile.
STUB_MENU = {
    "outlet_id": STUB_OUTLET_ID,
    "outlet_name": "Stub Kitchen",
    "categories": [
        {
            "name": "Mains",
            "items": [
                {"name": "Masala Dosa", "price": 90.0, "is_veg": True, "is_available": True},
                {"name": "Sold Out Curry", "price": 150.0, "is_veg": False, "is_available": False},
            ],
        },
        {
            "name": "Desserts",
            "items": [
                {"name": "Gulab Jamun", "price": 60.0, "is_veg": True, "is_available": True},
            ],
        },
    ],
}


class _StubHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802  (stdlib naming)
        if self.path == "/api/v1/public/outlets":
            body, code = STUB_OUTLETS, 200
        elif self.path == f"/api/v1/public/outlets/{STUB_OUTLET_ID}/menu":
            body, code = STUB_MENU, 200
        else:
            # Anything else — including a request that tried to reach a
            # non-public path — is a 404, matching the real backend.
            body, code = {"detail": "Outlet not found"}, 404
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):  # silence per-request logging
        pass


@contextmanager
def stub_backend():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


async def main() -> int:
    with stub_backend() as base_url:
        return await _run(base_url)


async def _run(base_url: str) -> int:
    # Inherit the real environment (the subprocess still needs PATH and the
    # interpreter's own variables) and point only the API base at the stub.
    env = dict(os.environ)
    env["CAREVO_API_BASE"] = base_url

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "carevo_mcp"],
        cwd=str(REPO),
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"\nServer: {init.server_info.name} v{init.server_info.version}\n")

            print("TOOL DISCOVERY")
            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            print(f"  list_tools() -> {names}")
            check(
                "registered tools are exactly the expected set",
                set(names) == EXPECTED_TOOLS,
                f"unexpected: {set(names) ^ EXPECTED_TOOLS}",
            )
            for want in sorted(EXPECTED_TOOLS):
                check(f"{want} is discoverable", want in names)
            check(
                "no order/payment/PII tools registered",
                not [n for n in names if n in FORBIDDEN],
                f"registered: {names}",
            )
            # Belt and braces: no tool NAME may even suggest a write. Catches a
            # future `create_*`/`update_*` that the FORBIDDEN list never
            # anticipated by exact name.
            write_ish = [
                n for n in names
                if n.split("_")[0] in {
                    "create", "update", "delete", "set", "place", "pay",
                    "cancel", "refund", "post", "add", "remove",
                }
            ]
            check("no tool name implies a write", not write_ish, f"got {write_ish}")

            tool = next(t for t in listed.tools if t.name == "get_carevo_info")
            schema = tool.input_schema or {}
            check(
                "takes no parameters",
                not schema.get("properties") and not schema.get("required"),
                f"inputSchema={json.dumps(schema)}",
            )
            check("has a description", bool(tool.description))

            print("\nTOOL CALL")
            result = await session.call_tool("get_carevo_info", {})
            check("call did not error", not result.is_error)

            payload = result.structured_content or json.loads(result.content[0].text)
            print(json.dumps(payload, indent=2, ensure_ascii=False))

            check("company.name", payload["company"]["name"] == "CareVo")
            check(
                "company.registration",
                payload["company"]["registration"]
                == "MSME-registered sole proprietorship",
            )
            check("company.country", payload["company"]["country"] == "India")
            check("product.name", payload["product"]["name"] == "Gusto Skip")

            for key, want in EXPECTED_FOUNDER.items():
                got = payload["founder"].get(key)
                check(f"founder.{key} == {want!r}", got == want, f"got {got!r}")

            # The numbers must be verbatim digits — no country code was added,
            # because no display convention existed in the repo to justify one.
            for key in ("whatsapp", "phone"):
                v = payload["founder"][key]
                check(
                    f"founder.{key} is plain digits, no prefix",
                    v.isdigit() and not v.startswith("+") and not v.startswith("91"),
                    f"got {v!r}",
                )

            print("\nLINKS")
            links = payload.get("links", {})
            check(
                "links has exactly the expected keys",
                set(links) == set(EXPECTED_LINKS),
                f"got {sorted(links)}",
            )
            for key, (want_label, want_url) in EXPECTED_LINKS.items():
                entry = links.get(key, {})
                check(
                    f"links.{key}.label == {want_label!r}",
                    entry.get("label") == want_label,
                    f"got {entry.get('label')!r}",
                )
                check(
                    f"links.{key}.url == {want_url!r}",
                    entry.get("url") == want_url,
                    f"got {entry.get('url')!r}",
                )
                check(
                    f"links.{key}.url is https",
                    str(entry.get("url", "")).startswith("https://"),
                    f"got {entry.get('url')!r}",
                )

            # The Play listing is not public yet. Until it is, the payload must
            # SAY so — a bare url here would have a language model telling a
            # real person to install from a page that 404s. When the app goes
            # live, delete the status key in info.py and this assertion.
            check(
                "android_app carries a not-yet-published status",
                bool(links.get("android_app", {}).get("status")),
                f"got {links.get('android_app', {}).get('status')!r}",
            )
            # The two live sites must NOT carry one, or the signal is noise.
            for key in ("company", "product"):
                check(
                    f"links.{key} has no status (it is live)",
                    "status" not in links.get(key, {}),
                    f"got {links.get(key, {}).get('status')!r}",
                )

            print("\nCATALOGUE TOOLS (against the stub backend)")
            lo = await session.call_tool("list_outlets", {})
            check("list_outlets did not error", not lo.is_error)
            lo_payload = lo.structured_content or json.loads(lo.content[0].text)
            check(
                "list_outlets reported no backend error",
                "error" not in lo_payload,
                f"got {lo_payload.get('error')!r}",
            )
            check("list_outlets count", lo_payload.get("count") == 1, f"got {lo_payload.get('count')}")
            got_outlet = (lo_payload.get("outlets") or [{}])[0]
            check(
                "outlet fields survive the round trip exactly",
                set(got_outlet) == set(STUB_OUTLETS[0]),
                f"got {sorted(got_outlet)}",
            )
            check("outlet name", got_outlet.get("name") == "Stub Kitchen")
            check("outlet open_status", got_outlet.get("open_status") == "open")
            # The tool must not invent or drop PII-adjacent fields.
            for forbidden in ("phone_number", "organization_id", "geofence_radius_meters"):
                check(f"outlet has no {forbidden}", forbidden not in got_outlet)

            gm = await session.call_tool("get_menu", {"outlet_id": STUB_OUTLET_ID})
            check("get_menu did not error", not gm.is_error)
            gm_payload = gm.structured_content or json.loads(gm.content[0].text)
            check(
                "get_menu reported no backend error",
                "error" not in gm_payload,
                f"got {gm_payload.get('error')!r}",
            )
            check("get_menu outlet_name", gm_payload.get("outlet_name") == "Stub Kitchen")
            check("get_menu category_count", gm_payload.get("category_count") == 2,
                  f"got {gm_payload.get('category_count')}")
            check("get_menu item_count sums across sections",
                  gm_payload.get("item_count") == 3, f"got {gm_payload.get('item_count')}")

            cats = gm_payload.get("categories", [])
            check("category fields exact",
                  all(set(c) == {"name", "items"} for c in cats),
                  f"got {[sorted(c) for c in cats]}")
            check("category order preserved",
                  [c["name"] for c in cats] == ["Mains", "Desserts"],
                  f"got {[c.get('name') for c in cats]}")

            # THE round-trip proof: every item must arrive under the same
            # category it was served in, with byte-identical fields. Comparing
            # the whole nested structure catches a regrouping that keeps the
            # right items but puts them in the wrong section — which a flat
            # name->item lookup would happily miss.
            check(
                "categories round-trip byte-identical to what the backend served",
                cats == STUB_MENU["categories"],
                f"got {json.dumps(cats)}",
            )

            by_name = {i["name"]: i for c in cats for i in c["items"]}
            check("menu item fields exact",
                  all(set(i) == {"name", "price", "is_veg", "is_available"} for i in by_name.values()),
                  f"got {[sorted(i) for i in by_name.values()]}")
            check("priced correctly", by_name.get("Masala Dosa", {}).get("price") == 90.0)
            # A sold-out item must be PRESENT and flagged, not filtered away —
            # the backend publishes it deliberately and the tool must not
            # quietly tidy it up.
            check(
                "sold-out item is present and flagged",
                by_name.get("Sold Out Curry", {}).get("is_available") is False,
                f"got {by_name.get('Sold Out Curry')}",
            )
            check("dessert landed in Desserts, not Mains",
                  [i["name"] for i in cats[1]["items"]] == ["Gulab Jamun"],
                  f"got {cats[1] if len(cats) > 1 else cats}")
            check("no description field invented",
                  all("description" not in i for i in by_name.values())
                  and all("description" not in c for c in cats))

            print("\nERROR HANDLING")
            bad = await session.call_tool("get_menu", {"outlet_id": "99999999-9999-4999-8999-999999999999"})
            bad_payload = bad.structured_content or json.loads(bad.content[0].text)
            check(
                "unknown outlet returns a usable message, not a crash",
                bool(bad_payload.get("error")) and bad_payload.get("categories") == [],
                f"got {bad_payload}",
            )

            print("\nIDEMPOTENCE / ISOLATION")
            payload["founder"]["email"] = "mutated@example.com"
            # Nested: catches a shallow dict() copy of `links`, which would
            # share the inner per-link objects with the module literal.
            payload["links"]["company"]["url"] = "https://evil.example.com"
            again = await session.call_tool("get_carevo_info", {})
            second = again.structured_content or json.loads(again.content[0].text)
            check(
                "a caller's mutation cannot leak into the next response",
                second["founder"]["email"] == "adithya@carevo.co.in",
                f"got {second['founder']['email']!r}",
            )
            check(
                "a caller's NESTED link mutation cannot leak either",
                second["links"]["company"]["url"] == "https://carevo.co.in",
                f"got {second['links']['company']['url']!r}",
            )

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
