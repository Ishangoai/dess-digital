import os

import uvicorn
from fastapi import APIRouter, FastAPI

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


app.include_router(api)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
