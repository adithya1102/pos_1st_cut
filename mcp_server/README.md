# CareVo MCP server

Read-only MCP server exposing public CareVo / Gusto Skip information.

**No order placement, no payment, no customer PII.** That is a property of
what is registered rather than a rule to remember — a tool that does not exist
cannot be called. `tests/test_client.py` pins the registered tool set
*exactly*, rejects the forbidden names, and additionally rejects any tool whose
name begins with a write verb (`create_`, `update_`, `delete_`, `set_`, …), so
a future write tool fails the suite rather than slipping through.

Two further boundaries hold the same line:

- `carevo_mcp/catalogue.py` can only build URLs under `/api/v1/public`. There
  is no generic "call the backend" helper for a later tool to reach for.
- It reads **no credentials** from the environment, so a token cannot be
  picked up by accident on a shared host. The endpoints it reads are
  unauthenticated by design and publish only hand-written field lists.

## Tools

| Tool | Params | Auth | Source |
|---|---|---|---|
| `get_carevo_info` | none | none | static (`carevo_mcp/info.py`) |
| `list_outlets` | none | none | `GET /api/v1/public/outlets` |
| `get_menu` | `outlet_id` | none | `GET /api/v1/public/outlets/{id}/menu` |

`list_outlets` returns each outlet's `id`, `name`, `city`, `latitude`,
`longitude`, `opens_at`, `closes_at`, `open_status` and `open_reason`. Use the
returned `id` with `get_menu`.

`get_menu` returns items **grouped into categories** — each category has a
`name` and its own `items`, and each item has `name`, `price`, `is_veg` and
`is_available`. Sold-out items are present and flagged rather than filtered
out. There is no `description` field: `menu_items` has no such column.

## Install

```bash
cd mcp_server
pip install .
```

Or, equivalently:

```bash
pip install -r requirements.txt
```

Both install the same three dependencies (`mcp`, `httpx`, `uvicorn`).
`pyproject.toml` is authoritative; `requirements.txt` mirrors its constraints
and **must be edited alongside it** — the two drifted once and the result was a
requirements-only environment where `import carevo_mcp.server` failed on a
missing `httpx`, invisible on any machine that already had it.

## Run

Two transports, same tools, from one definition. Only the byte transport
differs.

```bash
# stdio — what Claude Desktop launches. The default.
python -m carevo_mcp

# streamable-http — a persistent web service
carevo-mcp --transport streamable-http
python -m carevo_mcp --transport streamable-http   # same thing, no console script
```

An alternative for hosts that want to own the server process and its worker
model rather than let the SDK call `uvicorn.run()` itself. `--factory` is
required: `http_app` is a function returning the Starlette app, not the app.

```bash
uvicorn carevo_mcp.server:http_app --factory --host 0.0.0.0 --port 8080
```

### Environment

| Variable | Default | Notes |
|---|---|---|
| `CAREVO_API_BASE` | `https://gusto-pos-backend.onrender.com` | Backend for the catalogue tools. Default is live; override for local dev (`http://localhost:8000`). |
| `CAREVO_MCP_TRANSPORT` | `stdio` | Set to `streamable-http` to serve over HTTP, instead of passing `--transport`. |
| `PORT` | → `CAREVO_MCP_PORT` → `8080` | Read first; most PaaS inject it. |
| `CAREVO_MCP_PORT` | `8080` | Only consulted when `PORT` is unset. |
| `CAREVO_MCP_HOST` | `0.0.0.0` | Already correct for a container deploy. |
| `CAREVO_MCP_PATH` | `/mcp` | HTTP path the MCP endpoint is served at. |
| `CAREVO_MCP_ALLOWED_HOSTS` | *(unset)* | Comma-separated Host allow-list. **See below.** |

### Deploying remotely — read this one

The MCP SDK installs DNS-rebinding protection *only* when the bind host is
loopback. When it is `0.0.0.0` — which is what binding in a container requires
— it installs **nothing**, and the `Host` header stops being checked at exactly
the point the server becomes publicly reachable.

So set the allow-list explicitly:

```
CAREVO_MCP_ALLOWED_HOSTS=your-service.onrender.com
```

Entries may be `example.com` or `example.com:*`; matching `https://` origins
are derived automatically. Left unset, protection stays **off** rather than
being guessed at — an allow-list that does not contain the real domain rejects
every request with an opaque 421 and looks exactly like a broken deployment.

### Render

```
Root Directory:  mcp_server
Build command:   pip install .
Start command:   carevo-mcp --transport streamable-http
Environment:     CAREVO_MCP_TRANSPORT=streamable-http
                 CAREVO_MCP_ALLOWED_HOSTS=<your-service>.onrender.com
```

Root Directory matters: the build otherwise runs at the repository root, where
there is no `pyproject.toml`. `PORT` is injected by the platform — do not set
it. `CAREVO_API_BASE` can be left unset; its default is the live backend.

## Test

```bash
cd mcp_server
python tests/test_client.py          # stdio transport
python tests/test_http_transport.py  # streamable-http transport
```

Both spawn the server as a real subprocess and drive it as a real MCP client —
the stdio suite over stdio, the HTTP suite over a real port — because
registration and transport are the parts that actually break, and calling the
Python functions directly would prove neither.

`test_client.py` runs the catalogue tools against a local stub backend, so it
needs no database and does not depend on production being up. It compares the
whole nested menu structure byte-for-byte, which catches a regrouping that
keeps the right items but files them under the wrong category.

## Layout

```
mcp_server/
├── carevo_mcp/
│   ├── __init__.py     intentionally empty (avoids a double import)
│   ├── __main__.py     python -m carevo_mcp
│   ├── info.py         the static about-us content
│   ├── catalogue.py    HTTP client for /api/v1/public/* — the only
│   │                   backend path this server can construct
│   └── server.py       MCPServer instance, tool registration, both transports
├── tests/
│   ├── test_client.py         stdio end-to-end + stub backend
│   └── test_http_transport.py streamable-http end-to-end
├── pyproject.toml
├── requirements.txt    mirrors pyproject's dependencies — edit together
└── README.md
```

New static content goes in `info.py`; new tools go in `server.py`. Anything
reading live data belongs in neither until it has a reviewed, read-only
endpoint behind it — and it must go through `catalogue.py`, so the
public-path-only restriction keeps holding.
