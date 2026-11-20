"""Label each edit before anything is learned from it (DESS-051).

Cheap cases are labelled in code; the rest get one model call per agenda item, in parallel.
Every call is recorded with the run, so it shows in the AI activity view.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import LLMClient, LLMError, LLMResponse
from app.minutes import edit_labels as labels
from app.minutes.llm_schemas import (
    DraftMinutes,
    EvidenceAnalysis,
    EvidenceMap,
    ItemSelectionResult,
    PolicySelection,
)
from app.models.draft import DraftRun, LLMCall
from app.models.edits import EditClassification, EditedDocument
from app.models.profile import utcnow
from app.services import profile as profile_svc
from app.services.draft import bundle_for


def classify(db: Session, llm: LLMClient, run: DraftRun, edited: EditedDocument) -> EditedDocument:
    content = profile_svc.version_content(run.profile_version)
    draft = DraftMinutes.model_validate(run.draft)
    names = labels.attendee_names(draft.header)
    comments = {c["id"]: c["text"] for c in edited.comments}
    headings = {s["item_ref"]: s["heading"] for s in edited.sections}

    edited.classifications.clear()
    pending: dict[str, list[labels.Hunk]] = {}
    for h in labels.hunks(edited.alignments):
        code = labels.code_label(h, names, content.presentation)
        if code is None:
            pending.setdefault(h.row.item_ref, []).append(h)
            continue
        edited.classifications.append(
            _row(
                edited,
                h,
                "code",
                {
                    "kind": code.kind,
                    "dimensions": code.dimensions,
                    "cause": code.cause,
                    "support": labels.Support.NOT_APPLICABLE,
                    "evidence": [],
                    "profile_basis": code.profile_basis,
                    "pattern": code.pattern,
                    "reason": code.reason,
                },
            )
        )

    system = f"{labels.CLASSIFY_PREAMBLE}\n\n{content.logic}"
    jobs = [
        (ref, _message(run, ref, headings.get(ref, ref), item_hunks, comments))
        for ref, item_hunks in pending.items()
    ]

    def call(job: tuple[str, str]) -> LLMResponse[labels.EditLabels] | LLMError:
        try:
            return llm.generate_structured(
                job[1],
                schema=labels.EditLabels,
                system=system,
                max_tokens=settings.minutes_max_output_tokens,
            )
        except LLMError as e:
            return e

    with ThreadPoolExecutor(max(1, settings.minutes_parallel_calls)) as pool:
        results = list(pool.map(call, jobs))

    errors = []
    for (ref, message), result in zip(jobs, results, strict=True):
        stage = f"classify:{ref}"[:32]
        if isinstance(result, LLMError):
            errors.append(f"item {ref}: {result}")
            run.llm_calls.append(
                LLMCall(
                    stage=stage,
                    provider=llm.provider.name,
                    model=llm.model,
                    ok=False,
                    error=str(result),
                    system_prompt=system,
                    prompt=message,
                )
            )
            continue
        run.llm_calls.append(
            LLMCall(
                stage=stage,
                provider=result.provider,
                model=result.model,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=round(result.latency_ms),
                system_prompt=system,
                prompt=message,
                output=result.output.model_dump_json(),
            )
        )
        unlabelled = {h.edit_id: h for h in pending[ref]}
        for label in result.output.labels:
            if (h := unlabelled.pop(label.edit_id, None)) is not None:
                fields = label.model_dump(exclude={"edit_id"})
                edited.classifications.append(_row(edited, h, "model", fields))
        if unlabelled:
            errors.append(f"item {ref}: no label for {', '.join(sorted(unlabelled))}")

    edited.classified_at = utcnow()
    edited.classify_error = "; ".join(errors) or None
    db.commit()
    db.refresh(edited)
    return edited


def _row(
    edited: EditedDocument, h: labels.Hunk, source: str, f: dict[str, Any]
) -> EditClassification:
    cause = labels.EditCause(f["cause"])
    return EditClassification(
        edited_id=edited.id,
        alignment_id=h.row.id,
        hunk=h.index,
        before=h.before,
        after=h.after,
        source=source,
        kind=str(f["kind"]),
        dimensions=[str(d) for d in f["dimensions"]],
        cause=str(cause),
        support=str(f["support"]),
        evidence=f["evidence"],
        profile_basis=f["profile_basis"],
        pattern=str(f["pattern"])[:255],
        reason=f["reason"],
        route=str(labels.ROUTES[cause]),
    )


def _message(
    run: DraftRun, ref: str, heading: str, item_hunks: list[labels.Hunk], comments: dict[str, str]
) -> str:
    """The item, its evidence and Stage 2 selection, then its edits and the task."""
    bundle = bundle_for(run)
    parts = [f"<item>\n{ref}: {heading}\n</item>"]
    refs = []
    if ref == "header" and run.analysis:
        refs = EvidenceAnalysis.model_validate(run.analysis).particulars.refs
    elif run.mapping:
        refs = [
            s.source for s in EvidenceMap.model_validate(run.mapping).segments if s.item_ref == ref
        ]
    if refs:
        parts.append(f"<item_evidence>\n{bundle.lines_for(refs)}\n</item_evidence>")
    if run.selection:
        selection = PolicySelection.model_validate(run.selection)
        mine = next((i for i in selection.items if i.item_ref == ref), None)
        if mine is not None:
            asked = [c for c in selection.clarifications if c.item_ref == ref]
            chosen = ItemSelectionResult(selection=mine, clarifications=asked)
            parts.append(f"<selection>\n{chosen.model_dump_json(indent=1)}\n</selection>")
    parts.append(f"<edits>\n{labels.edits_block(item_hunks, comments)}\n</edits>")
    parts.append(f"<task>\n{labels.TASK_CLASSIFY.strip()}\n</task>")
    return "\n\n".join(parts)


def classify_in_background(bind: Engine | Connection, edited_id: uuid.UUID, llm: LLMClient) -> None:
    """Classify an uploaded copy after the upload response (FastAPI BackgroundTasks).

    Uses its own session: the request's session is closed by the time this runs.
    """
    with Session(bind) as db:
        edited = db.get(EditedDocument, edited_id)
        if edited is None:
            return
        try:
            classify(db, llm, edited.run, edited)
        except Exception as e:  # never leave it looking as if it is still working
            db.rollback()
            edited.classify_error = f"classification failed: {e}"
            db.commit()
