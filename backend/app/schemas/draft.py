import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from app.minutes.evidence import MeetingInfo, SourceRole
from app.minutes.llm_schemas import (
    DraftMinutes,
    EvidenceAnalysis,
    EvidenceMap,
    LineRef,
    PolicySelection,
    Reconsideration,
    ValidationReport,
)
from app.models.draft import DraftRun, DraftStatus
from app.services.draft import bundle_for


class DocumentOut(BaseModel):
    source_id: str
    role: SourceRole
    filename: str
    line_count: int


class LLMCallOut(BaseModel):
    id: uuid.UUID
    stage: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    ok: bool
    error: str | None
    created_at: datetime


class LLMCallDetail(LLMCallOut):
    """One call in full: instructions, message and response."""

    system_prompt: str | None
    prompt: str | None
    output: str | None
    raw_output: str | None


class UsageTotal(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int


class DraftRunSummary(BaseModel):
    id: uuid.UUID
    status: DraftStatus
    profile_slug: str
    profile_version: int
    meeting_info: MeetingInfo
    title: str
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def of(cls, run: DraftRun) -> "DraftRunSummary":
        info = MeetingInfo.model_validate(run.meeting_info or {})
        return cls(
            id=run.id,
            status=run.status,
            profile_slug=run.profile_version.profile.slug,
            profile_version=run.profile_version.version_number,
            meeting_info=info,
            title=_title(run, info),
            created_at=run.created_at,
            completed_at=run.completed_at,
        )


def _title(run: DraftRun, info: MeetingInfo) -> str:
    """Display name: entered details, else the drafted title, else the agenda filename."""
    entered = ": ".join(p for p in (info.organisation, info.body_name) if p)
    if entered:
        return entered
    drafted = ((run.draft or {}).get("header") or {}).get("title")
    if drafted:
        return drafted
    agenda = next((d.filename for d in run.documents if d.role == "agenda"), None)
    if agenda:
        return Path(agenda).stem.replace("_", " ")
    return "Untitled meeting"


class DraftRunOut(DraftRunSummary):
    documents: list[DocumentOut]
    analysis: EvidenceAnalysis | None
    mapping: EvidenceMap | None
    mapping_edited: bool
    draft: DraftMinutes | None
    lint: list[str]
    blocked_reasons: list[str]
    error: str | None
    error_stage: str | None
    llm_calls: list[LLMCallOut]
    usage_total: UsageTotal
    # Intermediate stages, only with ?debug=true
    selection: PolicySelection | None = None
    draft_initial: DraftMinutes | None = None
    validation: ValidationReport | None = None
    reconsideration: Reconsideration | None = None

    @classmethod
    def of(cls, run: DraftRun, debug: bool = False) -> "DraftRunOut":
        calls = [LLMCallOut.model_validate(c, from_attributes=True) for c in run.llm_calls]
        out = cls(
            **DraftRunSummary.of(run).model_dump(),
            documents=[DocumentOut.model_validate(d, from_attributes=True) for d in run.documents],
            analysis=_load(EvidenceAnalysis, run.analysis),
            mapping=_load(EvidenceMap, run.mapping),
            mapping_edited=run.mapping_edited,
            draft=_load(DraftMinutes, run.draft),
            lint=run.lint or [],
            blocked_reasons=run.blocked_reasons or [],
            error=run.error,
            error_stage=run.error_stage,
            llm_calls=calls,
            usage_total=UsageTotal(
                input_tokens=sum(c.input_tokens for c in calls),
                output_tokens=sum(c.output_tokens for c in calls),
                total_tokens=sum(c.input_tokens + c.output_tokens for c in calls),
                latency_ms=sum(c.latency_ms for c in calls),
            ),
        )
        if debug:
            out.selection = _load(PolicySelection, run.selection)
            out.draft_initial = _load(DraftMinutes, run.draft_initial)
            out.validation = _load(ValidationReport, run.validation)
            out.reconsideration = _load(Reconsideration, run.reconsideration)
        return out


class SegmentReview(BaseModel):
    segment_id: str
    source: LineRef
    item_ref: str | None
    association: str
    summary: str
    excerpt: str


class MappingReview(BaseModel):
    """The proposed mapping with excerpts, for the reviewer."""

    status: DraftStatus
    mapping: EvidenceMap
    valid_item_refs: list[str]
    segments: list[SegmentReview]
    uncovered: list[LineRef]
    uncovered_excerpts: list[str]

    @classmethod
    def of(cls, run: DraftRun) -> "MappingReview":
        mapping = EvidenceMap.model_validate(run.mapping)
        bundle = bundle_for(run)
        uncovered = bundle.uncovered(
            [s.source for s in mapping.segments], roles=(SourceRole.TRANSCRIPT, SourceRole.NOTES)
        )
        return cls(
            status=run.status,
            mapping=mapping,
            valid_item_refs=[i.ref for i in mapping.agenda_items]
            + [b.key for b in mapping.additional_business],
            segments=[
                SegmentReview(
                    segment_id=s.segment_id,
                    source=s.source,
                    item_ref=s.item_ref,
                    association=s.association,
                    summary=s.summary,
                    excerpt=bundle.excerpt(s.source),
                )
                for s in mapping.segments
            ],
            uncovered=uncovered,
            uncovered_excerpts=[bundle.excerpt(r, 300) for r in uncovered],
        )


def _load[T: BaseModel](model: type[T], data: object) -> T | None:
    return model.model_validate(data) if data is not None else None
