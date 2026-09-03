# Gusto Testing Dashboard (login-gated proxy)

A small FastAPI app that puts a **real login** and a **server-side secret** in
front of the main backend's `/api/v1/testing/*` routes.

- The browser only ever talks to this app's same-origin `/api/*` routes.
- This app holds `TESTING_DASHBOARD_KEY` server-side and attaches the
  `X-Testing-Key` header when it calls the backend. **The key is never sent to
  the browser** in any page, script, or response.
- Access is gated by a username/password login → signed-cookie session.

## Run locally

```bash
cd gusto_pos/dashboard_app
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env with real values
#   DASHBOARD_USER / DASHBOARD_PASS = the agreed login (kept out of
#   this repo; see the mission brief / your Render env)
#   TESTING_DASHBOARD_KEY=<same value set on the backend>
#   BACKEND_URL=https://gusto-pos-backend.onrender.com
#   SESSION_SECRET=<long random>
# load .env into the environment (or use a tool like `dotenv`), then:
uvicorn main:app --reload --port 8080
```

Open http://localhost:8080 → log in.

> The backend must ALSO have `TESTING_DASHBOARD_KEY` set to the same value, and
> the `testing_dashboard` module deployed, or every `/api/*` call returns 401/404.

## Deploy to Render (new service — NOT merged into the backend)

Create a **separate** Render Web Service:

1. **New → Web Service**, connect the same repo.
2. **Root Directory:** `gusto_pos/dashboard_app`
3. **Runtime:** Python 3
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. **Environment variables** (Settings → Environment):
   - `DASHBOARD_USER` = `gusto`
   - `DASHBOARD_PASS` = *(the agreed password — not written in this repo)*
   - `TESTING_DASHBOARD_KEY` = *(the exact value set on the backend service)*
   - `BACKEND_URL` = `https://gusto-pos-backend.onrender.com`
   - `SESSION_SECRET` = *(a long random string)*
7. Deploy.

Also required, on the **existing backend** service (one-time), before any of
this works against production:
- Set `TESTING_DASHBOARD_KEY` to the same value used above.
- Deploy the backend with the `testing_dashboard` module included (it currently
  returns 404 in production because that code is not yet shipped).

Nothing here is deployed automatically — this is a
paste-the-env-vars-and-click-deploy step for the account owner.
