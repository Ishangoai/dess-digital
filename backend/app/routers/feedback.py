"""Draft feedback scores. Mounted only when MINUTES_ROUTES=true (the API has no auth yet)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.feedback import ScoreOut
from app.services import feedback as svc

router = APIRouter(prefix="/feedback", tags=["Draft feedback"])

DB = Annotated[Session, Depends(get_db)]


@router.get("/scores")
def get_scores(db: DB) -> list[ScoreOut]:
    """Approvals and revisions per setup (profile version and model), best first."""
    return [ScoreOut.model_validate(s) for s in svc.scores(db)]
