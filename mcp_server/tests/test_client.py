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
import sys
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

# Tools that must NEVER appear. The server is read-only by construction, but
# an assertion makes a future regression loud instead of quiet.
FORBIDDEN = (
    "create_order", "place_order", "pay", "checkout", "capture_payment",
    "get_customer", "list_customers", "get_user", "search_customers",
)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "carevo_mcp"],
        cwd=str(REPO),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"\nServer: {init.server_info.name} v{init.server_info.version}\n")

            print("TOOL DISCOVERY")
            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            print(f"  list_tools() -> {names}")
            check("get_carevo_info is discoverable", "get_carevo_info" in names)
            check(
                "no order/payment/PII tools registered",
                not [n for n in names if n in FORBIDDEN],
                f"registered: {names}",
            )

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

            print("\nIDEMPOTENCE / ISOLATION")
            payload["founder"]["email"] = "mutated@example.com"
            again = await session.call_tool("get_carevo_info", {})
            second = again.structured_content or json.loads(again.content[0].text)
            check(
                "a caller's mutation cannot leak into the next response",
                second["founder"]["email"] == "adithya@carevo.co.in",
                f"got {second['founder']['email']!r}",
            )

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
