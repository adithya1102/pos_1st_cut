# Gusto POS — Backend

Run locally with Docker and Uvicorn.

Prereqs: Docker, Python 3.11

Install dependencies (optional if using Docker):

```powershell
cd gusto_pos/backend
python -m pip install -r requirements.txt
```

Start Postgres and app with Docker Compose:

```powershell
cd gusto_pos/backend
docker-compose up -d db
docker-compose up -d web
```

Or run app locally after installing deps:

```powershell
cd gusto_pos/backend
set PYTHONPATH=%CD%
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs
# Gusto POS Backend

Quickstart:

1. Start services:

```powershell
cd gusto_pos/backend
docker-compose up -d db
```

2. Install Python deps (optional if using Docker):

```powershell
python -m pip install -r requirements.txt
```

3. Start app locally:

```powershell
cd gusto_pos/backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs
