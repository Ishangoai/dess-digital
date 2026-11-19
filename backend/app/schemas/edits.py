import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.minutes.edit_labels import Finding, group_findings
from app.models.edits import EditClassification, EditedDocument


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hunk: int
    before: str
    after: str
    source: str
    kind: str
    dimensions: list[str]
    cause: str
    support: str
    evidence: list[dict[str, Any]]
    profile_basis: str | None
    reason: str
    pattern: str
    route: str


class AlignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    item_ref: str
    original_item_ref: str | None
    original_n: int | None
    paragraph_id: str | None
    role: str
    status: str
    similarity: float
    original_text: str
    final_text: str
    diff: list[dict[str, Any]]
    tracked: list[dict[str, Any]]
    comment_ids: list[str]
    labels: list[LabelOut] = []


class EditedSummary(BaseModel):
    id: uuid.UUID
    filename: str
    created_at: datetime
    created_by: str | None
    similarity: float
    export_id: uuid.UUID
    original_recreated: bool  # no stored download was found, so the original was rendered again
    counts: dict[str, int]  # paragraphs per status
    classified_at: datetime | None

    @classmethod
    def of(cls, e: EditedDocument) -> "EditedSummary":
        counts: dict[str, int] = {}
        for a in e.alignments:
            counts[a.status] = counts.get(a.status, 0) + 1
        return cls(
            id=e.id,
            filename=e.filename,
            created_at=e.created_at,
            created_by=e.created_by,
            similarity=e.similarity,
            export_id=e.export_id,
            original_recreated=e.export.recreated,
            counts=counts,
            classified_at=e.classified_at,
        )


class EditReview(EditedSummary):
    sections: list[dict[str, Any]]
    paragraphs: list[AlignmentOut]
    comments: list[dict[str, Any]]
    answers: list[dict[str, Any]]
    findings: list[Finding]
    classify_error: str | None

    @classmethod
    def of(cls, e: EditedDocument) -> "EditReview":
        by_row: dict[uuid.UUID, list[EditClassification]] = {}
        for c in e.classifications:
            by_row.setdefault(c.alignment_id, []).append(c)
        paragraphs = []
        for a in e.alignments:
            row = AlignmentOut.model_validate(a)
            row.labels = [
                LabelOut.model_validate(c)
                for c in sorted(by_row.get(a.id, []), key=lambda c: c.hunk)
            ]
            paragraphs.append(row)
        return cls(
            **EditedSummary.of(e).model_dump(),
            sections=e.sections,
            paragraphs=paragraphs,
            comments=e.comments,
            answers=e.answers,
            findings=group_findings(e.classifications),
            classify_error=e.classify_error,
        )
