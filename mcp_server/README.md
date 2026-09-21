# CareVo MCP server

Read-only MCP server exposing public CareVo / Gusto Skip information.

**No order placement, no payment, no customer PII.** That is a property of
what is registered rather than a rule to remember — a tool that does not exist
cannot be called. `tests/test_client.py` asserts the forbidden tool names are
absent, so adding one later fails the test rather than slipping through.

## Tools

| Tool | Params | Auth | Source |
|---|---|---|---|
| `get_carevo_info` | none | none | static (`carevo_mcp/info.py`) |

### Not yet built

The menu and location tools (`list_outlets`, `get_menu`, …) are **not** here.
They read from the `gusto_pos/backend` API, and wiring them up depends on the
endpoint audit — specifically the auth findings from it — not on this server.
`get_carevo_info` is deliberately independent of all of that: it answers from a
Python literal, so it neither needs the backend to be running nor waits on the
audit.

## Run

```bash
cd mcp_server
pip install -r requirements.txt
python -m carevo_mcp            # stdio transport
```

Requires `mcp>=2.1.1,<3`. The 2.0 release renamed `FastMCP` to `MCPServer`;
`server.py` uses the new name, so a `mcp<2` environment fails loudly at import
rather than running against a different API.

## Test

```bash
cd mcp_server
python tests/test_client.py
```

Spawns the server as a subprocess and drives it as a real MCP client over
stdio — the same path Developer Mode uses. It checks registration and
discovery, not just the Python function, because registration is the part that
actually breaks.

## Register in Developer Mode

Add to your MCP client config, with an absolute `cwd`:

```json
{
  "mcpServers": {
    "carevo": {
      "command": "python",
      "args": ["-m", "carevo_mcp"],
      "cwd": "C:\\Users\\Adithya\\Desktop\\demo2\\mcp_server"
    }
  }
}
```

`get_carevo_info` then appears in the tool list. Once the read-only menu and
location tools are added to `server.py`, they are discovered through the same
listing with no config change.

## Layout

```
mcp_server/
├── carevo_mcp/
│   ├── __init__.py     intentionally empty (avoids a double import)
│   ├── __main__.py     python -m carevo_mcp
│   ├── info.py         the static about-us content
│   └── server.py       MCPServer instance + tool registration
├── tests/test_client.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

New static content goes in `info.py`; new tools go in `server.py`. Anything
that reads live data belongs in neither until it has a reviewed, read-only
endpoint behind it.
