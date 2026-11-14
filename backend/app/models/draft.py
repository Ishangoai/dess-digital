"""Draft runs: uploaded evidence, stage outputs and LLM usage."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType
from app.minutes.evidence import SourceRole
from app.models.profile import MinutesProfileVersion, str_enum, utcnow


class DraftStatus(StrEnum):
    ANALYSING = "analysing"
    AWAITING_MAPPING_REVIEW = "awaiting_mapping_review"
    BLOCKED = "blocked"  # essential input missing; no draft
    DRAFTING = "drafting"
    COMPLETED = "completed"
    FAILED = "failed"


class DraftRun(Base):
    __tablename__ = "draft_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("minutes_profile_versions.id"))
    status: Mapped[DraftStatus] = mapped_column(str_enum(DraftStatus))
    meeting_info: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    # Stage outputs as JSON, validated by the models in app.minutes.llm_schemas.
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    selection: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    draft_initial: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    reconsideration: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    lint: Mapped[list[str] | None] = mapped_column(JSONType)

    mapping_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reasons: Mapped[list[str] | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    error_stage: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile_version: Mapped[MinutesProfileVersion] = relationship()
    documents: Mapped[list["DraftDocument"]] = relationship(
        back_populates="run", order_by="DraftDocument.position", cascade="all, delete-orphan"
    )
    llm_calls: Mapped[list["LLMCall"]] = relationship(
        back_populates="run", order_by="LLMCall.created_at", cascade="all, delete-orphan"
    )


class DraftDocument(Base):
    __tablename__ = "draft_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft_runs.id"))
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[SourceRole] = mapped_column(str_enum(SourceRole))
    source_id: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    line_count: Mapped[int] = mapped_column(Integer)

    run: Mapped[DraftRun] = relationship(back_populates="documents")


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft_runs.id"))
    stage: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    raw_output: Mapped[str | None] = mapped_column(Text)  # kept only when parsing failed
    # What was sent and received, for the AI activity view.
    # Deferred: large, and only loaded by GET /api/drafts/{id}/calls.
    system_prompt: Mapped[str | None] = mapped_column(Text, deferred=True)
    prompt: Mapped[str | None] = mapped_column(Text, deferred=True)
    output: Mapped[str | None] = mapped_column(Text, deferred=True)  # structured response, JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[DraftRun] = relationship(back_populates="llm_calls")
