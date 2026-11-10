# dess-digital

Self-hostable document processing app. Runs on a single VM with Docker Compose.

## Layout

- `backend/` FastAPI API (`app/main.py`) and background worker (`app/worker.py`). uv, pytest, ruff, ty.
- `frontend/` SvelteKit static SPA built with bun, served by Caddy which proxies `/api` and handles HTTPS. Playwright e2e.
- `docker-compose.yml` `db` (Postgres), `api`, `worker`, `web`. Files and Postgres data live under `DATA_DIR`.

## Run locally

```bash
cp .env.example .env
docker compose up --build   # http://localhost:8080
```

Dev without Docker:

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload   # :8000, docs at /api/docs
cd frontend && bun install && bun run dev                       # :5173, proxies /api
```

The backend needs a database. Either run Postgres in Docker:

```bash
docker run -d --name dess-pg -e POSTGRES_USER=dess -e POSTGRES_PASSWORD=dess -e POSTGRES_DB=dess -p 5432:5432 postgres:17-alpine
```

or set `DATABASE_URL=sqlite:///./data/dev.db` in `backend/.env` for a zero-setup local database. Tables are created on startup.

Minutes profiles (`/api/profiles`, enable with `MINUTES_ROUTES=true`) are loaded from a local file. The DESS Standard text is client material, so it lives in the gitignored `reference/` folder and is never committed:

```bash
cd backend && uv run python -m app.seed_profile ../reference/profiles/dess_standard.yaml --confirm
```

## Checks

```bash
cd backend && uv run ruff check && uv run ty check && uv run pytest
cd frontend && bun run check && bun run test:e2e
```

## Deploy

Push to `development`: `.github/workflows/deploy.yml` builds both images, pushes to Artifact Registry, then over IAP SSH writes `.env` to the VM and runs `docker compose up -d`.

GitHub `development` environment needs:

- secrets: `GCP_PROJECT_NAME`, `GCP_PROJECT_NUMBER`, `POSTGRES_PASSWORD`, `LLM_API_KEY` (not needed for `vertex` / `anthropic_vertex`)
- vars: `LLM_PROVIDER` (`openai` | `azure` | `gemini` | `vertex` | `anthropic` | `anthropic_vertex`), `LLM_MODEL`, `GCP_LOCATION` (optional, default `global`), `AZURE_ENDPOINT` (azure only), `SITE_ADDRESS` (domain pointing at the VM; empty means plain HTTP)

LLM calls go through `backend/app/llm`. The team default is `LLM_PROVIDER=gemini` with an AI Studio key.

VM name and zone are set at the top of the workflow.
