"""Draft runs: upload evidence, map it to the agenda, then generate the minutes."""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import LLMClient
from app.minutes.checks import validate_mapping
from app.minutes.docx_export import render_minutes_docx
from app.minutes.evidence import (
    EvidenceBundle,
    MeetingInfo,
    SourceRole,
    SourceText,
    source_ids_for,
)
from app.minutes.extract import UnsupportedFileError, extract_text
from app.minutes.llm_schemas import DraftMinutes, EvidenceAnalysis, EvidenceMap
from app.minutes.pipeline import Pipeline, PipelineStage, StageError, StageResult
from app.minutes.prompts import PromptContext
from app.models.draft import DraftDocument, DraftRun, DraftStatus, LLMCall
from app.models.profile import MinutesProfileVersion, utcnow
from app.services import profile as profile_svc

RAW_OUTPUT_LIMIT = 20_000


class DraftError(Exception):
    pass


class DraftNotFoundError(DraftError):
    pass


class InvalidInputError(DraftError):
    pass


class InputTooLargeError(DraftError):
    pass


class InvalidStateError(DraftError):
    pass


class MappingError(DraftError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Upload:
    role: SourceRole
    filename: str
    data: bytes


# creating a run


def create_run(
    db: Session,
    llm: LLMClient,
    uploads: list[Upload],
    *,
    meeting_info: MeetingInfo,
    profile_slug: str,
    profile_version: int | None = None,
) -> DraftRun:
    """Store the evidence and run stage 1 (evidence analysis and mapping)."""
    roles = [u.role for u in uploads]
    if SourceRole.AGENDA not in roles:
        raise InvalidInputError("an agenda is required")
    if SourceRole.TRANSCRIPT not in roles and SourceRole.NOTES not in roles:
        raise InvalidInputError("a transcript or meeting notes are required")

    version = _profile_version(db, profile_slug, profile_version)
    order = {SourceRole.AGENDA: 0, SourceRole.TRANSCRIPT: 1, SourceRole.NOTES: 2}
    uploads = sorted(uploads, key=lambda u: order.get(u.role, 3))
    texts = [extract_text(u.filename, u.data) for u in uploads]
    for u, text in zip(uploads, texts, strict=True):
        if not text.strip():
            raise InvalidInputError(f"{u.filename} contains no text")
    if sum(len(t) for t in texts) > settings.minutes_max_input_chars:
        raise InputTooLargeError(
            f"evidence exceeds {settings.minutes_max_input_chars:,} characters"
        )

    run = DraftRun(
        profile_version_id=version.id,
        status=DraftStatus.ANALYSING,
        meeting_info=meeting_info.model_dump(),
    )
    source_ids = source_ids_for(u.role for u in uploads)
    for position, (u, sid, text) in enumerate(zip(uploads, source_ids, texts, strict=True)):
        run.documents.append(
            DraftDocument(
                position=position,
                role=u.role,
                source_id=sid,
                filename=u.filename,
                sha256=hashlib.sha256(u.data).hexdigest(),
                text=text,
                line_count=len(text.split("\n")),
            )
        )
    db.add(run)
    db.commit()

    pipeline = _pipeline(run, llm)
    try:
        result = pipeline.analyse_evidence()
    except StageError as e:
        _record_failure(db, run, llm, e)
        return run

    _record_call(db, run, result)
    analysis = result.output
    run.analysis = analysis.model_dump(mode="json")
    run.mapping = analysis.evidence_map().model_dump(mode="json")
    if analysis.essential_input_problems:
        run.status = DraftStatus.BLOCKED
        run.blocked_reasons = [
            f"{p.kind}: {p.description}" for p in analysis.essential_input_problems
        ]
    else:
        run.status = DraftStatus.AWAITING_MAPPING_REVIEW
    db.commit()
    return run


def _profile_version(db: Session, slug: str, number: int | None) -> MinutesProfileVersion:
    try:
        profile = profile_svc.get_profile(db, slug)
        if number is not None:
            return profile_svc.get_version(profile, number)
    except profile_svc.ProfileError as e:
        raise InvalidInputError(str(e)) from e
    active = profile_svc.active_version(profile)
    if active is None:
        raise InvalidInputError(f"profile '{slug}' has no confirmed version")
    return active


# reading


def get_run(db: Session, run_id: uuid.UUID) -> DraftRun:
    run = db.get(DraftRun, run_id)
    if run is None:
        raise DraftNotFoundError(f"draft run {run_id} not found")
    return run


def list_runs(db: Session, offset: int = 0, limit: int = 20) -> list[DraftRun]:
    query = select(DraftRun).order_by(DraftRun.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(query))


def bundle_for(run: DraftRun) -> EvidenceBundle:
    return EvidenceBundle(
        [SourceText(d.source_id, d.role, d.filename, d.text) for d in run.documents]
    )


# mapping review


def update_mapping(db: Session, run: DraftRun, mapping: EvidenceMap) -> DraftRun:
    if run.status != DraftStatus.AWAITING_MAPPING_REVIEW:
        raise InvalidStateError(f"mapping can only be changed while reviewing (now {run.status})")
    errors = validate_mapping(mapping, bundle_for(run))
    if errors:
        raise MappingError(errors)
    run.mapping = mapping.model_dump(mode="json")
    run.mapping_edited = True
    db.commit()
    return run


# generation


def generate(
    db: Session, llm: LLMClient, run: DraftRun, mapping: EvidenceMap | None = None
) -> DraftRun:
    """Run stages 2-4 and store the draft. The mapping, if given, is saved first."""
    if mapping is not None:
        update_mapping(db, run, mapping)

    retry_failed = run.status == DraftStatus.FAILED and run.error_stage not in {
        None,
        PipelineStage.EVIDENCE,
    }
    allowed = [DraftStatus.AWAITING_MAPPING_REVIEW] + ([DraftStatus.FAILED] if retry_failed else [])
    # Claim the run atomically so a double click cannot start two drafts.
    claimed = cast(
        CursorResult[Any],
        db.execute(
            update(DraftRun)
            .where(DraftRun.id == run.id, DraftRun.status.in_(allowed))
            .values(status=DraftStatus.DRAFTING, error=None, error_stage=None)
        ),
    )
    db.commit()
    if claimed.rowcount != 1:
        db.refresh(run)
        raise InvalidStateError(f"cannot generate a draft from status {run.status}")
    db.refresh(run)

    assert run.mapping is not None and run.analysis is not None
    pipeline = _pipeline(run, llm)
    stage_columns = {
        PipelineStage.POLICY: "selection",
        PipelineStage.STYLE: "draft_initial",
        PipelineStage.VALIDATION: "validation",
        PipelineStage.RECONSIDERATION: "reconsideration",
    }

    def on_stage(result: StageResult[Any]) -> None:
        setattr(run, stage_columns[result.stage], result.output.model_dump(mode="json"))
        _record_call(db, run, result)
        db.commit()

    try:
        result = pipeline.run_drafting(
            EvidenceMap.model_validate(run.mapping),
            EvidenceAnalysis.model_validate(run.analysis),
            on_stage=on_stage,
        )
    except StageError as e:
        _record_failure(db, run, llm, e)
        return run

    run.draft = result.draft.model_dump(mode="json")
    run.lint = [str(i) for i in result.lint]
    run.status = DraftStatus.COMPLETED
    run.completed_at = utcnow()
    db.commit()
    return run


def render_document(run: DraftRun, template: bytes | None = None) -> bytes:
    """The completed draft as a Word document, optionally built into a user template."""
    if run.draft is None:
        raise InvalidStateError(f"no draft yet (status {run.status})")
    presentation = profile_svc.version_content(run.profile_version).presentation
    try:
        return render_minutes_docx(DraftMinutes.model_validate(run.draft), presentation, template)
    except UnsupportedFileError:
        raise
    except Exception as e:  # python-docx raises several unrelated types for bad templates
        raise UnsupportedFileError(f"template is not a readable .docx file: {e}") from e


def _pipeline(run: DraftRun, llm: LLMClient) -> Pipeline:
    ctx = PromptContext(
        profile=profile_svc.version_content(run.profile_version),
        bundle=bundle_for(run),
        meeting_info=MeetingInfo.model_validate(run.meeting_info or {}),
    )
    return Pipeline(llm, ctx, max_tokens=settings.minutes_max_output_tokens)


def _record_call(db: Session, run: DraftRun, result: StageResult[Any]) -> None:
    run.llm_calls.append(
        LLMCall(
            stage=result.stage,
            provider=result.provider,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            latency_ms=round(result.latency_ms),
        )
    )


def _record_failure(db: Session, run: DraftRun, llm: LLMClient, e: StageError) -> None:
    run.llm_calls.append(
        LLMCall(
            stage=e.stage,
            provider=llm.provider.name,
            model=llm.model,
            ok=False,
            error=str(e.cause),
            raw_output=e.raw_text[:RAW_OUTPUT_LIMIT] if e.raw_text else None,
        )
    )
    run.status = DraftStatus.FAILED
    run.error = str(e)
    run.error_stage = e.stage
    db.commit()
