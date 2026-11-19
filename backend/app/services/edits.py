"""Stored Word exports, and edited copies compared with them."""

import dataclasses
import hashlib
import uuid

from sqlalchemy.orm import Session

from app.minutes.docx_compare import Comparison, compare, read_docx
from app.minutes.docx_export import IDENTIFIER_PREFIX, ExportManifest, render_minutes
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import DraftMinutes
from app.models.draft import DocumentComparison, DraftRun, EditedDocument, ExportedDocument
from app.services import profile as profile_svc
from app.services.draft import InvalidStateError


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
