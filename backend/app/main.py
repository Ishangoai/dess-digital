import logging
import os

import uvicorn
from fastapi import APIRouter, FastAPI

from app.config import settings
from app.routers import draft, files, job, llm, profile

# Root handler so app loggers (e.g. app.llm prompt/token logs) reach stdout under uvicorn.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="dess-digital",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redirect_slashes=False,
)
api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(files.router)
api.include_router(job.router)
if settings.llm_test_routes:
    api.include_router(llm.router)
if settings.minutes_routes:
    api.include_router(profile.router)
    api.include_router(draft.router)

app.include_router(api)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
