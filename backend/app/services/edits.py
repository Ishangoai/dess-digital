"""Stored Word exports, and edited copies compared with them."""

import dataclasses
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import CursorResult, or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import LLMClient, LLMError, LLMOutputValidationError, LLMResponse
from app.minutes import edit_review
from app.minutes.docx_compare import Comparison, compare, read_docx
from app.minutes.docx_export import IDENTIFIER_PREFIX, ExportManifest, render_minutes
from app.minutes.edit_review import EditClassificationResult, EditReview
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import DraftMinutes, EvidenceMap, PolicySelection
from app.models.draft import (
    ClassificationStatus,
    DocumentComparison,
    DraftRun,
    EditedDocument,
    ExportedDocument,
    LLMCall,
)
from app.models.profile import utcnow
from app.services import profile as profile_svc
from app.services.draft import InvalidStateError, bundle_for

EDIT_REVIEW_STAGE = "edit_review"
EDIT_REVIEW_WORKERS = 4  # model calls run in parallel


def export_document(db: Session, run: DraftRun, template: bytes | None = None) -> ExportedDocument:
    """Render the draft as Word, store the file and return it."""
    if run.draft is None:
        raise InvalidStateError(f"no draft yet (status {run.status})")
    presentation = profile_svc.version_content(run.profile_version).presentation
    export_id = uuid.uuid4()
    try:
        rendered = render_minutes(
            DraftMinutes.model_validate(run.draft),
            presentation,
            template,
            identifier=f"{IDENTIFIER_PREFIX}{export_id}",
        )
    except Exception as e:  # python-docx raises several unrelated types for bad templates
        raise UnsupportedFileError(f"template is not a readable .docx file: {e}") from e
    export = ExportedDocument(
        id=export_id,
        data=rendered.data,
        sha256=hashlib.sha256(rendered.data).hexdigest(),
        used_template=template is not None,
        draft=run.draft,
        manifest=dataclasses.asdict(rendered.manifest),
    )
    run.exports.append(export)
    db.commit()
    return export


def upload_edited(db: Session, run: DraftRun, filename: str, data: bytes) -> EditedDocument:
    """Store an edited copy and compare it with the export it came from."""
    if run.draft is None:
        raise InvalidStateError(f"no draft yet (status {run.status})")
    probe = read_docx(data, ExportManifest())  # also rejects files that are not .docx
    export = _source_export(run, probe.export_id()) or export_document(db, run)
    manifest = ExportManifest(**export.manifest)
    original = read_docx(export.data, manifest)
    hints = [(b.heading_key, b.text) for b in original.blocks if b.heading_key]
    edited = read_docx(data, manifest, heading_hints=hints)
    result = compare(original, edited, manifest)

    document = EditedDocument(
        run_id=run.id,
        export=export,
        filename=filename,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        comparison=DocumentComparison(result=result.model_dump(mode="json")),
    )
    run.edited_documents.append(document)
    db.commit()
    return document


def latest_edited(run: DraftRun) -> EditedDocument | None:
    return run.edited_documents[-1] if run.edited_documents else None


def comparison_of(document: EditedDocument) -> Comparison:
    assert document.comparison is not None
    return Comparison.model_validate(document.comparison.result)


def _source_export(run: DraftRun, export_id: str | None) -> ExportedDocument | None:
    """The export named in the file's properties, else the run's latest export."""
    if export_id:
        try:
            wanted = uuid.UUID(export_id)
        except ValueError:
            wanted = None
        match = next((e for e in run.exports if e.id == wanted), None)
        if match is not None:
            return match
    return run.exports[-1] if run.exports else None


def classification_of(document: EditedDocument) -> EditClassificationResult | None:
    data = document.comparison.classification if document.comparison else None
    return EditClassificationResult.model_validate(data) if data else None


# explaining the edits (DESS-051)


def request_classification(db: Session, document: EditedDocument) -> bool:
    """Queue a classification. False if one is already running for this document."""
    row = document.comparison
    assert row is not None
    status = DocumentComparison.classification_status
    result = cast(
        CursorResult[Any],
        db.execute(
            update(DocumentComparison)
            .where(
                DocumentComparison.id == row.id,
                or_(status.is_(None), status != ClassificationStatus.RUNNING),
            )
            .values(classification_status=ClassificationStatus.PENDING, classification_error=None)
        ),
    )
    db.commit()
    db.refresh(row)
    return result.rowcount == 1


def classify(db: Session, llm: LLMClient, document: EditedDocument) -> DocumentComparison | None:
    """Settle the cheap edits in code and explain the rest, one model call per agenda item."""
    row = document.comparison
    assert row is not None
    claimed = cast(
        CursorResult[Any],
        db.execute(
            update(DocumentComparison)
            .where(
                DocumentComparison.id == row.id,
                DocumentComparison.classification_status == ClassificationStatus.PENDING,
            )
            .values(classification_status=ClassificationStatus.RUNNING)
        ),
    )
    db.commit()
    db.refresh(row)
    if claimed.rowcount != 1:
        return None  # not queued, or another worker took it

    run = document.run
    comparison = comparison_of(document)
    profile = profile_svc.version_content(run.profile_version)
    bundle = bundle_for(run)
    plan = edit_review.plan_review(
        comparison,
        DraftMinutes.model_validate(document.export.draft),
        profile,
        PolicySelection.model_validate(run.selection) if run.selection else None,
        EvidenceMap.model_validate(run.mapping) if run.mapping else None,
        bundle,
    )

    classified = list(plan.by_rule)
    errors: list[str] = []
    prompts = [r.message for r in plan.requests]
    for request, outcome in zip(
        plan.requests, call_each(llm, plan.system, EditReview, prompts), strict=True
    ):
        if isinstance(outcome, LLMError):
            record_failure(run, llm, EDIT_REVIEW_STAGE, plan.system, request.message, outcome)
            errors.append(f"item {request.section}: {outcome}")
            continue
        record_call(run, EDIT_REVIEW_STAGE, plan.system, request.message, outcome)
        classified += edit_review.accept_review(outcome.output, request, profile, bundle)

    wanted = [c for c in edit_review.ensure_change_ids(comparison) if edit_review.needs_review(c)]
    result = edit_review.build_result(classified, wanted)
    row.classification = result.model_dump(mode="json")
    row.classification_status = (
        ClassificationStatus.FAILED if errors else ClassificationStatus.COMPLETED
    )
    row.classification_error = "; ".join(errors) or None
    row.classified_at = utcnow()
    db.commit()
    return row


def call_each[T: BaseModel](
    llm: LLMClient, system: str, schema: type[T], prompts: list[str]
) -> list[LLMResponse[T] | LLMError]:
    """One structured call per prompt, a few at a time, in prompt order."""

    def call(prompt: str) -> LLMResponse[T] | LLMError:
        try:
            return llm.generate_structured(
                prompt,
                schema=schema,
                system=system,
                max_tokens=settings.minutes_max_output_tokens,
            )
        except LLMError as e:
            return e

    if not prompts:
        return []
    with ThreadPoolExecutor(max_workers=min(EDIT_REVIEW_WORKERS, len(prompts))) as pool:
        return list(pool.map(call, prompts))


def record_call(run: DraftRun, stage: str, system: str, prompt: str, r: LLMResponse[Any]) -> None:
    run.llm_calls.append(
        LLMCall(
            stage=stage,
            provider=r.provider,
            model=r.model,
            input_tokens=r.usage.input_tokens,
            output_tokens=r.usage.output_tokens,
            latency_ms=round(r.latency_ms),
            system_prompt=system,
            prompt=prompt,
            output=r.output.model_dump_json(),
        )
    )


def record_failure(
    run: DraftRun, llm: LLMClient, stage: str, system: str, prompt: str, e: LLMError
) -> None:
    raw = e.raw_text if isinstance(e, LLMOutputValidationError) else None
    run.llm_calls.append(
        LLMCall(
            stage=stage,
            provider=llm.provider.name,
            model=llm.model,
            ok=False,
            error=str(e),
            raw_output=raw[:20_000] if raw else None,
            system_prompt=system,
            prompt=prompt,
        )
    )
