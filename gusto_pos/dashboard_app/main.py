"""Login-gated testing dashboard — a small proxy in front of the main backend's
secret-gated /api/v1/testing/* routes.

WHY A SEPARATE APP (not the file:// page, not merged into the backend):
  * The secret (TESTING_DASHBOARD_KEY) must NEVER reach the browser. This app
    holds it as its OWN server env var and attaches the X-Testing-Key header
    itself when calling the backend. The browser only ever talks to THIS app's
    same-origin /api/* routes, which return plain data — the key is in no page,
    script, or response.
  * A real login (username/password → signed-cookie session) replaces the old
    "type the key into a local file" approach, so the tool can be deployed and
    shared without handing anyone the backend secret.

FastAPI was chosen over Node/Express: the repo is already FastAPI + httpx +
pytest, so this reuses the exact toolchain, deps, and test harness — no second
language or build system to deploy and maintain.

Env vars (set in Render, never hardcoded):
  DASHBOARD_USER, DASHBOARD_PASS  — login credentials, checked server-side.
  TESTING_DASHBOARD_KEY           — the backend's testing key, held only here.
  BACKEND_URL                     — main backend root, e.g. https://…onrender.com
  SESSION_SECRET                  — signs the session cookie.
"""
from __future__ import annotations

import os
import secrets

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "templates")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _template(name: str) -> str:
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return f.read()


app = FastAPI(title="Gusto Testing Dashboard")
# Signed-cookie session. The secret is server-side only; the cookie carries no
# readable data, just a signed marker that the user logged in.
app.add_middleware(
    SessionMiddleware,
    secret_key=_env("SESSION_SECRET", "dev-only-insecure-secret"),
    session_cookie="gusto_dash_session",
    https_only=False,  # Render terminates TLS; the app sees http internally.
    same_site="lax",
)


# --------------------------------- auth -----------------------------------
def _credentials_ok(username: str, password: str) -> bool:
    """Constant-time check against the env credentials. FAIL-CLOSED: if either
    env var is unset, no login succeeds."""
    u, p = _env("DASHBOARD_USER"), _env("DASHBOARD_PASS")
    if not u or not p:
        return False
    return (secrets.compare_digest(username, u)
            and secrets.compare_digest(password, p))


def require_session(request: Request):
    """API guard: 401 when there is no valid session."""
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not authenticated")


def _backend_client() -> httpx.AsyncClient:
    """httpx client pre-loaded with the secret header. Isolated in one factory
    so tests can substitute a MockTransport and inspect the OUTBOUND header."""
    return httpx.AsyncClient(
        base_url=_env("BACKEND_URL").rstrip("/") + "/api/v1/testing",
        headers={"X-Testing-Key": _env("TESTING_DASHBOARD_KEY")},
        timeout=90,
    )


async def _proxy(method: str, path: str, json_body=None) -> JSONResponse:
    """Call the backend's testing route and hand the browser ONLY the data.
    The X-Testing-Key lives on the outbound request and never in the response."""
    async with _backend_client() as client:
        r = await client.request(method, path, json=json_body)
    try:
        payload = r.json()
    except Exception:
        payload = {"detail": r.text}
    return JSONResponse(status_code=r.status_code, content=payload)


# --------------------------------- pages ----------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    html = _template("login.html").replace(
        "{{ERROR}}", "Wrong username or password." if error else "")
    return HTMLResponse(html)


@app.post("/login")
async def login_submit(request: Request,
                       username: str = Form(...), password: str = Form(...)):
    if not _credentials_ok(username, password):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=303)
    # The dashboard HTML contains NO secret — it only calls this app's /api/*.
    return HTMLResponse(_template("dashboard.html"))


# ------------------------- proxied data routes ----------------------------
# All require a session; all attach the key server-side.
@app.get("/api/outlets")
async def api_outlets(_=Depends(require_session)):
    return await _proxy("GET", "/outlets")


@app.get("/api/orders")
async def api_orders(_=Depends(require_session)):
    return await _proxy("GET", "/orders")


@app.get("/api/compliance")
async def api_compliance(_=Depends(require_session)):
    return await _proxy("GET", "/compliance")


@app.post("/api/orders/{order_id}/approve")
async def api_approve_order(order_id: str, _=Depends(require_session)):
    # Proxies to the backend's testing approve route, which reuses the real
    # advance_status. Key attached server-side, never sent to the browser.
    return await _proxy("POST", f"/orders/{order_id}/approve")


@app.post("/api/orders/{order_id}/reject")
async def api_reject_order(order_id: str, request: Request,
                          _=Depends(require_session)):
    try:
        body = await request.json()
    except Exception:
        body = None
    return await _proxy("POST", f"/orders/{order_id}/reject", json_body=body)


@app.get("/api/testers")
async def api_testers(_=Depends(require_session)):
    return await _proxy("GET", "/testers")


@app.post("/api/testers")
async def api_add_tester(request: Request, _=Depends(require_session)):
    return await _proxy("POST", "/testers", json_body=await request.json())


@app.delete("/api/testers/{identifier:path}")
async def api_remove_tester(identifier: str, _=Depends(require_session)):
    return await _proxy("DELETE", f"/testers/{identifier}")


@app.patch("/api/labels/{identifier:path}")
async def api_set_label(identifier: str, request: Request,
                        _=Depends(require_session)):
    return await _proxy("PATCH", f"/labels/{identifier}",
                        json_body=await request.json())


@app.get("/healthz")
async def healthz():
    return {"ok": True}
