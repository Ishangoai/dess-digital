"""Draft runs: upload evidence, map it to the agenda, then generate the minutes."""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import Connection, CursorResult, Engine, select, update
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
from app.minutes.profile_content import Provenance, ProvisionKind
from app.minutes.prompts import PromptContext
from app.models.amendment import ProfileAmendmentSet
from app.models.draft import DraftDocument, DraftRun, DraftStatus, LLMCall
from app.models.profile import MinutesProfileVersion, VersionOrigin, utcnow
from app.services import amendment as amend_svc
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
    analyse: bool = True,
) -> DraftRun:
    """Store the evidence and run stage 1 (evidence analysis and mapping).

    With analyse=False the run is stored as analysing and returned at once; call
    analyse_in_background to run stage 1.
    """
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

    return _analyse(db, llm, run) if analyse else run


def analyse_in_background(
    bind: Engine | Connection, run_id: uuid.UUID, llm: LLMClient, then_draft: bool = False
) -> None:
    """Stage 1 for a stored run, after the upload response (FastAPI BackgroundTasks).

    Uses its own session: the request's session is closed by the time this runs.
    """
    with Session(bind) as db:
        run = db.get(DraftRun, run_id)
        if run is None:
            return
        try:
            run = _analyse(db, llm, run)
            if then_draft and run.status == DraftStatus.AWAITING_MAPPING_REVIEW:
                generate(db, llm, run)
        except Exception as e:  # never leave the run stuck as analysing
            db.rollback()
            run.status = DraftStatus.FAILED
            run.error = str(e)
            run.error_stage = PipelineStage.EVIDENCE
            db.commit()


def retry_analysis(db: Session, llm: LLMClient, run: DraftRun) -> DraftRun:
    """Re-run stage 1 for a run whose analysis failed, reusing the uploaded files."""
    failed_analysis = run.status == DraftStatus.FAILED and run.error_stage == PipelineStage.EVIDENCE
    if not failed_analysis or not _claim(db, run, [DraftStatus.FAILED], DraftStatus.ANALYSING):
        raise InvalidStateError(f"only a failed analysis can be retried (status {run.status})")
    return _analyse(db, llm, run)


def _analyse(db: Session, llm: LLMClient, run: DraftRun) -> DraftRun:
    try:
        result = _pipeline(run, llm).analyse_evidence()
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
    if not _claim(db, run, allowed, DraftStatus.DRAFTING):
        hint = (
            " (analysis failed: retry it first)"
            if run.error_stage == PipelineStage.EVIDENCE
            else ""
        )
        raise InvalidStateError(f"cannot generate a draft from status {run.status}{hint}")

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

    if run.mapping_edited:
        learn_from_mapping_edits(db, llm, run)

    return run


# learning from mapping edits


def diff_mapping(original: EvidenceMap, edited: EvidenceMap) -> list[str]:
    orig_by_id = {s.segment_id: s for s in original.segments}
    edited_by_id = {s.segment_id: s for s in edited.segments}

    diffs: list[str] = []

    # Segments added by user
    for sid, es in edited_by_id.items():
        if sid not in orig_by_id:
            diffs.append(
                f"Added segment {sid} (source {es.source.source_id}, "
                f"lines {es.source.start}-{es.source.end}) "
                f"under Item '{es.item_ref or 'Unassigned'}' "
                f"with association '{es.association}': \"{es.summary}\""
            )

    # Segments removed by user
    for sid, os in orig_by_id.items():
        if sid not in edited_by_id:
            diffs.append(
                f"Removed segment {sid} (previously under Item '{os.item_ref or 'Unassigned'}', "
                f"association '{os.association}'): \"{os.summary}\""
            )

    # Segments modified by user
    for sid, es in edited_by_id.items():
        if sid in orig_by_id:
            os = orig_by_id[sid]
            changes = []
            if es.item_ref != os.item_ref:
                changes.append(
                    f"reassigned from Item '{os.item_ref or 'None'}' "
                    f"to Item '{es.item_ref or 'None'}'"                )
            if es.association != os.association:
                changes.append(f"association changed from '{os.association}' to '{es.association}'")
            if (es.source.start, es.source.end) != (os.source.start, os.source.end):
                changes.append(
                f"lines changed from {os.source.start}-{os.source.end} "
                f"to {es.source.start}-{es.source.end}"                )
            if es.summary != os.summary:
                changes.append(f'summary updated from "{os.summary}" to "{es.summary}"')
            if changes:
                diffs.append(
                    f"Segment {sid} ({es.source.source_id}:{es.source.start}-{es.source.end}): "
                    + "; ".join(changes)
                )

    return diffs


class LearnedProposalItem(BaseModel):
    target_dimension: str
    target_type: str = "provision"
    operation: str = "add"
    target_provision: str | None = None
    proposed_text: str
    reason: str
    evidence: str


class LearnedProposalsResponse(BaseModel):
    has_proposals: bool
    proposals: list[LearnedProposalItem] = Field(default_factory=list)


def learn_from_mapping_edits(
    db: Session,
    llm: LLMClient | None,
    run: DraftRun,
) -> ProfileAmendmentSet | None:
    """Analyze changes made to the evidence mapping and infer profile amendment proposals."""
    if not run.mapping_edited or not run.analysis or not run.mapping or llm is None:
        return None

    orig_map = EvidenceMap.model_validate(run.analysis)
    edited_map = EvidenceMap.model_validate(run.mapping)
    diffs = diff_mapping(orig_map, edited_map)
    if not diffs:
        return None

    meeting_title = (run.meeting_info or {}).get("title") or run.id.hex[:8]
    diff_text = "\n".join(f"- {d}" for d in diffs)

    prompt = (
        "You are an expert governance assistant helping to learn standing "
        "organisation preferences from human edits.\n\n"
        f"Meeting: {meeting_title}\n"
        "The governance professional manually made the following corrections "
        f"to the AI's evidence mapping:\n{diff_text}\n\n"
        "Analyze these editorial corrections. Infer what recurring Minuting "
        "Policy (MP1-MP9) or Writing Style (WS1-WS6) rule or preference the "
        "professional is enforcing (e.g. MP2 for evidential basis, MP3 for "
        "materiality thresholds, MP8 for procedural handling).\n"
        "Never alter or contradict evidential fundamentals.\n"
        "Generate 1 to 2 granular, actionable amendment proposals.\n"
        "Reply with has_proposals=true and the proposals, or "
        "has_proposals=false if no general rule can be inferred."
    )

    try:
        result = llm.generate_structured(prompt, LearnedProposalsResponse)
    except Exception:
        return None

    if not result.output.has_proposals or not result.output.proposals:
        return None

    proposals_payload = []
    for p in result.output.proposals:
        proposals_payload.append(
            {
                "target_dimension": p.target_dimension,
                "target_provision": p.target_provision,
                "target_type": p.target_type,
                "operation": p.operation,
                "proposed_text": p.proposed_text,
                "kind": ProvisionKind.PREFERENCE.value,
                "provenance": Provenance.INFERRED.value,
                "reason": p.reason,
                "evidence": p.evidence,
            }
        )

    title = f"Learned from mapping edits ({meeting_title})"
    try:
        aset = amend_svc.create_amendment_set(
            db,
            run.profile_version,
            origin=VersionOrigin.FEEDBACK,
            title=title,
            created_by="mapping-learner",
            proposals=proposals_payload,
            llm=llm,
        )
    except Exception:
        return None

    meeting_info = dict(run.meeting_info or {})
    meeting_info["learned_amendment_set_id"] = str(aset.id)
    run.meeting_info = meeting_info
    db.commit()
    db.refresh(run)

    return aset


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


def _claim(db: Session, run: DraftRun, allowed: list[DraftStatus], new: DraftStatus) -> bool:
    """Move the run to a new status atomically, so a double click cannot start it twice."""
    result = cast(
        CursorResult[Any],
        db.execute(
            update(DraftRun)
            .where(DraftRun.id == run.id, DraftRun.status.in_(allowed))
            .values(status=new, error=None, error_stage=None)
        ),
    )
    db.commit()
    db.refresh(run)
    return result.rowcount == 1


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
            system_prompt=result.system or None,
            prompt=result.message or None,
            output=result.output.model_dump_json(),
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
            system_prompt=e.system or None,
            prompt=e.message or None,
        )
    )
    run.status = DraftStatus.FAILED
    run.error = str(e)
    run.error_stage = e.stage
    db.commit()
