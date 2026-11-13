# dess-digital

Self-hostable document processing app. Runs on a single VM with Docker Compose.

## Layout

- `backend/` FastAPI API (`app/main.py`) and background worker (`app/worker.py`). uv, pytest, ruff, ty.
- `frontend/` SvelteKit static SPA built with bun, served by Caddy which proxies `/api` and handles HTTPS. Playwright e2e.
- `docker-compose.yml` `db` (Postgres), `api`, `worker`, `web`. Files and Postgres data live under `DATA_DIR` (defaults to `./data` when run locally).

## Run locally

```bash
cp .env.example .env
docker compose up --build   # http://localhost:8080
```

Dev without Docker:

```bash
# Terminal 1: Backend
cd backend && uv sync && uv run uvicorn app.main:app --reload   # :8000, docs at /api/docs

# Terminal 2: Frontend
cd frontend && bun install && bun run dev
```

## Checks

```bash
cd backend && uv run ruff check && uv run ty check && uv run pytest
cd frontend && bun run check && bun run test:e2e
```

## Deploy

Push to `development`: `.github/workflows/deploy.yml` builds both images, pushes to Artifact Registry, then over IAP SSH writes `.env` to the VM and runs `docker compose up -d`.

When self-hosting elsewhere, set `DATA_DIR` in `.env` to any host path (e.g., `/mnt/disks/data`)

GitHub `development` environment needs:

- secrets: `GCP_PROJECT_NAME`, `GCP_PROJECT_NUMBER`, `POSTGRES_PASSWORD`, `LLM_API_KEY`
- vars: `LLM_PROVIDER` (`vertex` | `bedrock` | `azure`), `LLM_MODEL`, `SITE_ADDRESS` (domain pointing at the VM; empty means plain HTTP)

VM name and zone are set at the top of the workflow.
