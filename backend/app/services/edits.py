"""The professional's edited Word copy (DESS-050): store every export, take the edited copy back,
line it up with the exact original paragraph by paragraph, and keep their comments and replies."""

import hashlib
import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.minutes.alignment import align
from app.minutes.docx_export import ParagraphMark, bookmark_name, render_for_review
from app.minutes.docx_read import ParsedDoc, read_docx
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import DraftMinutes
from app.minutes.profile_content import PresentationSettings
from app.minutes.roundtrip import ReviewerComment, WrongDraftError, summarise
from app.models.draft import DraftRun
from app.models.edits import EditAlignment, EditedDocument, ExportedDocument
from app.models.feedback import DraftFeedback, Verdict
from app.services import feedback as feedback_svc
from app.services import profile as profile_svc
from app.services.draft import InvalidStateError


def export_document(
    db: Session, run: DraftRun, template: bytes | None = None, recreated: bool = False
) -> ExportedDocument:
    """Render the Word draft and store the exact bytes: the original for any later comparison."""
    if run.draft is None:
        raise InvalidStateError(f"no draft yet (status {run.status})")
    presentation = profile_svc.version_content(run.profile_version).presentation
    export_id = uuid.uuid4()
    try:
        rendered = render_for_review(
            DraftMinutes.model_validate(run.draft),
            presentation,
            template,
            str(run.id),
            str(export_id),
        )
    except UnsupportedFileError:
        raise
    except Exception as e:  # python-docx raises several unrelated types for bad templates
        raise UnsupportedFileError(f"template is not a readable .docx file: {e}") from e
    record = ExportedDocument(
        id=export_id,
        run_id=run.id,
        filename=f"draft-minutes-{run.id.hex[:8]}.docx",
        sha256=hashlib.sha256(rendered.data).hexdigest(),
        data=rendered.data,
        marks=[asdict(m) for m in rendered.marks],
        with_template=template is not None,
        recreated=recreated,
    )
    db.add(record)
    db.commit()
    return record


def upload_edited(
    db: Session, run: DraftRun, filename: str, data: bytes, by: str | None = None
) -> tuple[EditedDocument, DraftFeedback]:
    """Store the edited copy, line it up with its original, and score how much was kept."""
    feedback_svc.require_finished(run)
    if not filename.lower().endswith(".docx"):
        raise UnsupportedFileError(f"{filename}: upload the edited Word (.docx) file")
    draft = DraftMinutes.model_validate(run.draft)
    item_refs = {bookmark_name(i.item_ref): i.item_ref for i in draft.items}
    final = read_docx(data, item_refs)
    if final.run_id and final.run_id != str(run.id):
        raise WrongDraftError("this Word file was downloaded from a different draft")
    export = _original(db, run, final.export_id)
    original = read_docx(export.data, item_refs)
    alignment = align(original, [ParagraphMark(**m) for m in export.marks], final)

    presentation = profile_svc.version_content(run.profile_version).presentation
    comments, answers = _comments(final, draft, presentation, alignment.paragraphs)
    summary = summarise(
        alignment,
        [ReviewerComment(author=c["author"], text=c["text"]) for c in comments],
        final.run_id,
    )
    edited = EditedDocument(
        run_id=run.id,
        export_id=export.id,
        filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
        similarity=summary.similarity,
        sections=[s.model_dump() for s in alignment.sections],
        summary=summary.model_dump(mode="json"),
        comments=comments,
        answers=answers,
        created_by=by,
        alignments=[EditAlignment(**r.model_dump(mode="json")) for r in alignment.paragraphs],
    )
    db.add(edited)
    db.flush()
    feedback = feedback_svc.save(
        db,
        run,
        Verdict.EDITED,
        summary.similarity,
        filename=filename,
        comparison=summary.model_dump(mode="json"),
        edited_document_id=edited.id,
        by=by,
    )
    return edited, feedback


def list_edited(db: Session, run: DraftRun) -> list[EditedDocument]:
    stmt = (
        select(EditedDocument)
        .where(EditedDocument.run_id == run.id)
        .order_by(EditedDocument.created_at.desc())
    )
    return list(db.scalars(stmt))


def get_edited(db: Session, run: DraftRun, edited_id: uuid.UUID) -> EditedDocument:
    edited = db.get(EditedDocument, edited_id)
    if edited is None or edited.run_id != run.id:
        raise LookupError(f"edited copy {edited_id} not found for this draft")
    return edited


def _original(db: Session, run: DraftRun, export_id: str | None) -> ExportedDocument:
    """The export the copy came from; else the latest download; else render one now."""
    if export_id:
        try:
            found = db.get(ExportedDocument, uuid.UUID(export_id))
        except ValueError:
            found = None
        if found is not None:
            if found.run_id != run.id:
                raise WrongDraftError("this Word file was downloaded from a different draft")
            return found
    latest = db.scalar(
        select(ExportedDocument)
        .where(ExportedDocument.run_id == run.id)
        .order_by(ExportedDocument.created_at.desc())
        .limit(1)
    )
    return latest or export_document(db, run, recreated=True)


def _comments(
    final: ParsedDoc, draft: DraftMinutes, presentation: PresentationSettings, rows: list[Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The professional's comments, and their replies matched to our clarification questions."""
    ours = presentation.comment_author
    questions = {q.question.strip(): q for q in draft.questions}
    asked = {c.id: questions.get(c.text.strip()) for c in final.comments if c.author == ours}
    position = {cid: r.position for r in rows for cid in r.comment_ids}
    comments, answers = [], []
    for c in final.comments:
        if c.author == ours or not c.text:
            continue
        question = asked.get(c.parent_id or "")
        comments.append(
            {
                "id": c.id,
                "author": c.author,
                "text": c.text,
                "anchor": c.anchor,
                "position": position.get(c.id),
                "question_id": question.question_id if question else None,
            }
        )
        if question is not None:
            answers.append(
                {
                    "question_id": question.question_id,
                    "question": question.question,
                    "reply": c.text,
                    "author": c.author,
                }
            )
    return comments, answers
