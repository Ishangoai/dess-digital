"""Reviewer feedback on finished drafts: a vote, or the edited Word file they sent back."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType
from app.models.draft import DraftRun
from app.models.profile import MinutesProfileVersion, str_enum, utcnow


class Verdict(StrEnum):
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"
    EDITED = "edited"  # an edited copy was uploaded


# Rewards run from 0 to 1. An edited copy earns its similarity to the draft.
REWARDS = {Verdict.APPROVED: 1.0, Verdict.REVISION_REQUESTED: 0.0}


class DraftFeedback(Base):
    __tablename__ = "draft_feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft_runs.id"))
    verdict: Mapped[Verdict] = mapped_column(str_enum(Verdict))
    reward: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    # Only for an uploaded edit: the file name and the item-by-item comparison.
    filename: Mapped[str | None] = mapped_column(String(255))
    comparison: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    # The setup that wrote the draft, copied here so scores can be grouped by it.
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("minutes_profile_versions.id"))
    model: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[DraftRun] = relationship()
    profile_version: Mapped[MinutesProfileVersion] = relationship()
