"""The streamable-http transport, driven as a real HTTP client.

Companion to test_client.py, which covers the same server over stdio. Both
exist because the transport is the part that breaks when it changes: the tool
functions are identical either way, so a test that only ever spoke stdio would
pass just as happily with the HTTP entry point completely broken.

This one launches `python -m carevo_mcp --transport streamable-http` as a real
subprocess on a real port, connects over HTTP, and calls a tool. Nothing is
imported from the server module — if the entry point does not start, or binds
the wrong path, or never becomes reachable, this fails.

Run:  python tests/test_http_transport.py
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

REPO = Path(__file__).resolve().parent.parent

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def wait_until_listening(port: int, proc: subprocess.Popen, timeout: float = 45.0) -> bool:
    """Poll the port until the server accepts a connection.

    Also watches the child: a server that died on import would otherwise be
    indistinguishable from one that is merely slow, and the suite would sit
    here for the whole timeout before failing for the wrong reason.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with closing(socket.create_connection(("127.0.0.1", port), timeout=1.0)):
                return True
        except OSError:
            await asyncio.sleep(0.25)
    return False


async def main() -> int:
    port = free_port()
    env = dict(os.environ)
    # No stub backend here: this suite is about the transport, and
    # get_carevo_info answers from the static literal with no network at all.
    # The catalogue tools' HTTP path is covered in test_client.py.
    env["CAREVO_MCP_TRANSPORT"] = "streamable-http"
    env["CAREVO_MCP_HOST"] = "127.0.0.1"
    env["CAREVO_MCP_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "carevo_mcp"],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        print(f"\nLaunching streamable-http on 127.0.0.1:{port}")
        up = await wait_until_listening(port, proc)
        if not up:
            out = ""
            if proc.poll() is not None:
                out = (proc.stdout.read() if proc.stdout else "") or ""
            check("server started and is listening", False, out[-600:] or "timed out")
            return 1
        check("server started and is listening", True)

        url = f"http://127.0.0.1:{port}/mcp"
        async with streamable_http_client(url) as streams:
            # The transport yields (read, write) plus a session-id callback in
            # this SDK version; take the first two positionally so a third
            # element does not break the unpack.
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                check(
                    "initialize over HTTP",
                    init.server_info.name == "carevo",
                    f"got {init.server_info.name!r} v{init.server_info.version}",
                )

                listed = await session.list_tools()
                names = sorted(t.name for t in listed.tools)
                print(f"  list_tools() -> {names}")
                check(
                    "same tools as over stdio",
                    set(names) == {"get_carevo_info", "list_outlets", "get_menu"},
                    f"got {names}",
                )

                result = await session.call_tool("get_carevo_info", {})
                check("tool call over HTTP did not error", not result.is_error)
                payload = result.structured_content or json.loads(result.content[0].text)
                check(
                    "payload is identical to the stdio transport's",
                    payload["company"]["name"] == "CareVo"
                    and payload["links"]["company"]["url"] == "https://carevo.co.in",
                    f"got {payload.get('company')}",
                )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
