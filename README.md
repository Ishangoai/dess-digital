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

Minutes profiles (`/api/profiles`, enable with `MINUTES_ROUTES=true`) are markdown. The DESS Standard profile is `backend/app/minutes/profiles/dess_standard.md`: the Professional Standards and Operational AI Logic documents, word for word, sent to the model on every call. The compose `migrate` service seeds it on every deploy (a new version only when the file changed). Locally:

```bash
cd backend && uv run python -m app.seed_profile --confirm
```

To rebuild it from new versions of the DESS Word documents:

```bash
uv run python -m app.minutes.build_logic STANDARDS.docx OPS_LOGIC.docx
```

### Drafting minutes

With `MINUTES_ROUTES=true`, `LLM_MODEL` and `LLM_API_KEY` set in `backend/.env`:

```bash
cd backend
uv run uvicorn app.main:app --reload                  # API on :8000
uv run --group ui python -m dev_ui                    # Gradio dev UI on :7860
```

The flow is: upload agenda + transcript and/or notes, review the mapping of evidence to agenda items, generate, then download the Word draft (clarification questions are Word comments). Selecting content, writing and reconsidering run once per agenda item, in parallel (`MINUTES_PARALLEL_CALLS`, default 4), which keeps cheaper models from writing thin summaries.

### Review and learning

On the minutes page a reviewer can approve the draft, request a revision (with a reason), or edit the Word file and upload the final copy. The upload is matched back to the draft by the run id and bookmarks in the exported file and compared item by item. Every piece of feedback earns a reward from 0 to 1 (approve 1, revise 0, edited copy = share of the draft kept); **Draft scores** ranks each profile version and model by it.

Learning is per organisation: create an organisation profile (Minutes profiles page) based on the DESS Standard and draft that organisation's meetings with it. Its reviewers' final copies are shown to later drafts as house examples, and **Propose lessons from feedback** turns their edits, comments and revision reasons into a proposed profile version with house lessons. Nothing changes until a person confirms it. Before confirming, check the candidate against past finals:

```bash
uv run python -m evals.replay --profile <org-slug> --version <n> --limit 3 --out ../reference/replay
```

Without the API or database:

```bash
uv run python -m app.minutes.cli --agenda agenda.docx --transcript transcript.txt \
  --out ../reference/out
```

### Evaluating judgement

Runs cases through the real model (costs tokens) and checks the minutes apply judgement rather than summarise. Cases built from DESS material go in `reference/evals/cases`.

```bash
uv run python -m evals.minutes_eval evals/cases/*.yaml ../reference/evals/cases/*.yaml \
  --out ../reference/evals/out --repeat 2
```

### Comparing minutes

An LLM judge scores minutes of one meeting item by item against the profile (outcome, substance, challenge, actions, accuracy, style) and, with `--reference`, compares each with a gold copy in both orders. Minutes can be `.docx`, `.md` or a pipeline `draft.json`. Use a strong judge model.

```bash
uv run python -m evals.compare --agenda agenda.docx --transcript transcript.docx \
  --reference gold.docx --judge-model gemini-3.6-flash --out ../reference/compare out/*/draft.json
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
