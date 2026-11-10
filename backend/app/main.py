import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db import create_tables
from app.routers import draft, files, llm, profile

# Root handler so app loggers (e.g. app.llm prompt/token logs) reach stdout under uvicorn.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    if settings.db_create_tables:
        try:
            create_tables()
        except OperationalError:
            # Keep serving non-DB routes; DB routes will fail until the database is reachable.
            log.exception("could not create tables: is the database running? (DATABASE_URL)")
    yield


app = FastAPI(
    title="dess-digital",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redirect_slashes=False,
    lifespan=lifespan,
)
api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(files.router)
if settings.llm_test_routes:
    api.include_router(llm.router)
if settings.minutes_routes:
    api.include_router(profile.router)
    api.include_router(draft.router)

app.include_router(api)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
