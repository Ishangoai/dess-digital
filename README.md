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
# Terminal 1: Backend
cd backend && cp .env.example .env && uv sync && uv run uvicorn app.main:app --reload   # :8000, docs at /api/docs

# Terminal 2: Frontend
cd frontend && bun install && bun run dev
```

The backend needs a database. Either run Postgres in Docker:

```bash
docker run -d --name dess-pg -e POSTGRES_USER=dess -e POSTGRES_PASSWORD=dess -e POSTGRES_DB=dess -p 5432:5432 postgres:17-alpine
```

or set `DATABASE_URL=sqlite:///./data/dev.db` in `backend/.env` for a zero-setup local database. Then create the tables (and again after pulling new migrations):

```bash
cd backend && uv run alembic upgrade head
```

Docker Compose runs migrations automatically (the `migrate` service). After changing a model, add a migration with `uv run alembic revision --autogenerate -m "..."` and review it.

Minutes profiles (`/api/profiles`, enable with `MINUTES_ROUTES=true`) are loaded from a local file. The DESS Standard text is client material, so it lives in the gitignored `reference/` folder and is never committed:

```bash
cd backend && uv run python -m app.seed_profile ../reference/profiles/dess_standard.yaml --confirm
```

### Drafting minutes

With `MINUTES_ROUTES=true`, `LLM_MODEL` and `LLM_API_KEY` set in `backend/.env`:

```bash
cd backend
uv run uvicorn app.main:app --reload                  # API on :8000
uv run --group ui python -m dev_ui                    # Gradio dev UI on :7860
```

The flow is: upload agenda + transcript and/or notes, review the mapping of evidence to agenda items, generate, then download the Word draft (clarification questions are Word comments).

Without the API or database:

```bash
uv run python -m app.minutes.cli --profile ../reference/profiles/dess_standard.yaml \
  --agenda agenda.docx --transcript transcript.txt --out ../reference/out
```

### Evaluating judgement

Runs cases through the real model (costs tokens) and checks the minutes apply judgement rather than summarise. Cases built from DESS material go in `reference/evals/cases`.

```bash
uv run python -m evals.minutes_eval evals/cases/*.yaml ../reference/evals/cases/*.yaml \
  --profile ../reference/profiles/dess_standard.yaml --out ../reference/evals/out --repeat 2
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
