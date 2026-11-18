import logging
import os

import uvicorn
from fastapi import APIRouter, Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app.config import settings
from app.routers import auth, draft, files, job, llm, profile

# Root handler so app loggers (e.g. app.llm prompt/token logs) reach stdout under uvicorn.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="dess-digital",
    docs_url=None,
    openapi_url=None,
    redirect_slashes=False,
)
api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Public auth endpoints (/api/auth/login, /api/auth/logout)
api.include_router(auth.router)

# Protected routes
protected = APIRouter(dependencies=[Depends(auth.require_auth)])


@protected.get("/openapi.json", include_in_schema=False)
def openapi_schema():
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@protected.get("/docs", include_in_schema=False)
def swagger_ui():
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title=f"{app.title} - Docs")


protected.include_router(files.router)
protected.include_router(job.router)
if settings.llm_test_routes:
    protected.include_router(llm.router)
if settings.minutes_routes:
    protected.include_router(profile.router)
    protected.include_router(draft.router)

api.include_router(protected)
app.include_router(api)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
