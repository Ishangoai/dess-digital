"""The exact Word copies we exported, the edited copies sent back, and how they line up."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType
from app.models.draft import DraftRun
from app.models.profile import utcnow


class ExportedDocument(Base):
    """The .docx exactly as downloaded: the original an edited copy is compared with."""

    __tablename__ = "exported_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft_runs.id"))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    marks: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)  # hidden paragraph ids
    with_template: Mapped[bool] = mapped_column(default=False)
    # True when no download was stored and the original had to be rendered at upload time.
    recreated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[DraftRun] = relationship()


class EditedDocument(Base):
    """An edited copy the professional uploaded, with what was found in it."""

    __tablename__ = "edited_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft_runs.id"))
    export_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exported_documents.id"))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    similarity: Mapped[float] = mapped_column(Float)  # share of the draft kept, 0 to 1
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType)  # per item (roundtrip.Comparison)
    comments: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)  # the professional's
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)  # replies to our questions
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classify_error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[DraftRun] = relationship()
    export: Mapped[ExportedDocument] = relationship()
    alignments: Mapped[list["EditAlignment"]] = relationship(
        back_populates="edited", order_by="EditAlignment.position", cascade="all, delete-orphan"
    )
    classifications: Mapped[list["EditClassification"]] = relationship(
        back_populates="edited", cascade="all, delete-orphan"
    )


class EditAlignment(Base):
    """One paragraph of the original or the edited copy, and what happened to it."""

    __tablename__ = "edit_alignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    edited_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("edited_documents.id"))
    position: Mapped[int] = mapped_column(Integer)
    item_ref: Mapped[str] = mapped_column(String(64))
    original_item_ref: Mapped[str | None] = mapped_column(String(64))
    original_n: Mapped[int | None] = mapped_column(Integer)
    paragraph_id: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # alignment.ParagraphStatus
    similarity: Mapped[float] = mapped_column(Float)
    original_text: Mapped[str] = mapped_column(Text)
    final_text: Mapped[str] = mapped_column(Text)
    diff: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)
    tracked: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)
    comment_ids: Mapped[list[str]] = mapped_column(JSONType)

    edited: Mapped[EditedDocument] = relationship(back_populates="alignments")


class EditClassification(Base):
    """One edit inside a paragraph, labelled by kind, dimension and cause (DESS-051)."""

    __tablename__ = "edit_classifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    edited_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("edited_documents.id"))
    alignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("edit_alignments.id"))
    hunk: Mapped[int] = mapped_column(Integer)  # which change within the paragraph
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # code or model
    kind: Mapped[str] = mapped_column(String(32))
    dimensions: Mapped[list[str]] = mapped_column(JSONType)
    cause: Mapped[str] = mapped_column(String(32))
    support: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType)
    profile_basis: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    pattern: Mapped[str] = mapped_column(String(255))
    route: Mapped[str] = mapped_column(String(16))  # defect, meeting_only or candidate

    edited: Mapped[EditedDocument] = relationship(back_populates="classifications")
    alignment: Mapped[EditAlignment] = relationship()
