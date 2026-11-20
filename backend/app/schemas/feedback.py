import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.minutes.roundtrip import Comparison
from app.models.feedback import Verdict


class FeedbackIn(BaseModel):
    verdict: Verdict
    reason: str | None = Field(default=None, max_length=4000)
    by: str | None = Field(default=None, max_length=255)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    verdict: Verdict
    reward: float
    reason: str | None
    filename: str | None
    comparison: Comparison | None
    edited_document_id: uuid.UUID | None
    model: str
    created_by: str | None
    created_at: datetime


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_slug: str
    profile_version: int
    model: str
    approvals: int
    revisions: int
    edits: int
    votes: int
    net: int
    approval_rate: float
    mean_similarity: float | None
    expected: float
