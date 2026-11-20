"""Draft minutes API. Mounted only when MINUTES_ROUTES=true (the API has no auth yet)."""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.llm import LLMClient, get_llm_client
from app.minutes.amendments import AmendmentError
from app.minutes.docx_export import DOCX_MEDIA_TYPE
from app.minutes.evidence import MeetingInfo, SourceRole
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import EvidenceMap
from app.models.draft import ClassificationStatus, DraftRun, DraftStatus, EditedDocument
from app.schemas.draft import DraftRunOut, DraftRunSummary, LLMCallDetail, MappingReview
from app.schemas.edits import (
    AmendmentProposalOut,
    ApplyAmendments,
    EditedDocumentOut,
    ProposalUpdate,
)
from app.services import amendments as amendments_svc
from app.services import draft as svc
from app.services import edits as edits_svc
from app.services import profile as profile_svc

router = APIRouter(prefix="/drafts", tags=["Draft minutes"])

DB = Annotated[Session, Depends(get_db)]


def llm_client() -> LLMClient:
    try:
        return get_llm_client()
    except ValueError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LLM not configured: {e}") from e


LLM = Annotated[LLMClient, Depends(llm_client)]


def optional_llm_client() -> LLMClient | None:
    try:
        return get_llm_client()
    except ValueError:
        return None


OptionalLLM = Annotated[LLMClient | None, Depends(optional_llm_client)]


def _run(db: Session, run_id: uuid.UUID) -> DraftRun:
    try:
        return svc.get_run(db, run_id)
    except svc.DraftNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


async def _upload(role: SourceRole, file: UploadFile | None) -> svc.Upload | None:
    if file is None or not file.filename:
        return None
    data = await file.read(settings.minutes_max_upload_bytes + 1)
    if len(data) > settings.minutes_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"{file.filename} is larger than the upload limit"
        )
    return svc.Upload(role=role, filename=file.filename, data=data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(
    db: DB,
    llm: LLM,
    tasks: BackgroundTasks,
    agenda: Annotated[UploadFile, File(description="Agenda (required)")],
    transcript: Annotated[UploadFile | None, File()] = None,
    notes: Annotated[UploadFile | None, File()] = None,
    papers: Annotated[list[UploadFile] | None, File()] = None,
    profile_slug: Annotated[str | None, Form()] = None,
    profile_version: Annotated[int | None, Form()] = None,
    organisation: Annotated[str | None, Form()] = None,
    body_name: Annotated[str | None, Form()] = None,
    meeting_date: Annotated[str | None, Form()] = None,
    meeting_type: Annotated[str | None, Form()] = None,
    auto_confirm_mapping: Annotated[bool, Form()] = False,
    background: Annotated[bool, Form()] = False,
) -> DraftRunOut:
    """Upload the evidence and map it to the agenda. With auto_confirm_mapping, also draft.

    With background=true the run is returned at once with status analysing, and stage 1 runs
    after the response; poll GET /api/drafts/{id} to follow it.
    """
    uploads = [
        await _upload(SourceRole.AGENDA, agenda),
        await _upload(SourceRole.TRANSCRIPT, transcript),
        await _upload(SourceRole.NOTES, notes),
        *[await _upload(SourceRole.PAPER, p) for p in papers or []],
    ]
    info = MeetingInfo(
        organisation=organisation,
        body_name=body_name,
        meeting_date=meeting_date,
        meeting_type=meeting_type,
    )
    try:
        run = svc.create_run(
            db,
            llm,
            [u for u in uploads if u is not None],
            meeting_info=info,
            profile_slug=profile_slug or settings.minutes_default_profile,
            profile_version=profile_version,
            analyse=not background,
        )
        if background:
            tasks.add_task(
                svc.analyse_in_background, db.get_bind(), run.id, llm, auto_confirm_mapping
            )
        elif auto_confirm_mapping and run.status == DraftStatus.AWAITING_MAPPING_REVIEW:
            run = svc.generate(db, llm, run)
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    except svc.InputTooLargeError as e:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(e)) from e
    except svc.InvalidInputError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return DraftRunOut.of(run)


@router.get("")
def list_drafts(
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[DraftRunSummary]:
    return [DraftRunSummary.of(r) for r in svc.list_runs(db, offset, limit)]


@router.get("/{run_id}")
def get_draft(run_id: uuid.UUID, db: DB, debug: bool = False) -> DraftRunOut:
    """The run with its draft. debug=true adds the intermediate stage outputs."""
    return DraftRunOut.of(_run(db, run_id), debug=debug)


@router.get("/{run_id}/calls")
def get_calls(run_id: uuid.UUID, db: DB) -> list[LLMCallDetail]:
    """Every LLM call in full: the instructions and message sent, and the response."""
    return [
        LLMCallDetail.model_validate(c, from_attributes=True) for c in _run(db, run_id).llm_calls
    ]


@router.get("/{run_id}/mapping")
def get_mapping(run_id: uuid.UUID, db: DB) -> MappingReview:
    run = _run(db, run_id)
    if run.mapping is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"no mapping yet (status {run.status})")
    return MappingReview.of(run)


@router.put("/{run_id}/mapping")
def put_mapping(run_id: uuid.UUID, mapping: EvidenceMap, db: DB) -> MappingReview:
    run = _run(db, run_id)
    try:
        svc.update_mapping(db, run, mapping)
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except svc.MappingError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"mapping_errors": e.errors}
        ) from e
    return MappingReview.of(run)


@router.post("/{run_id}/analyse")
def retry_analysis(run_id: uuid.UUID, db: DB, llm: LLM) -> DraftRunOut:
    """Retry a failed evidence analysis without uploading the files again."""
    try:
        run = svc.retry_analysis(db, llm, _run(db, run_id))
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return DraftRunOut.of(run)


@router.post("/{run_id}/generate")
def generate_draft(
    run_id: uuid.UUID,
    db: DB,
    llm: LLM,
    mapping: Annotated[EvidenceMap | None, Body()] = None,
) -> DraftRunOut:
    """Confirm the mapping (optionally corrected) and draft the minutes."""
    run = _run(db, run_id)
    try:
        run = svc.generate(db, llm, run, mapping)
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except svc.MappingError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"mapping_errors": e.errors}
        ) from e
    return DraftRunOut.of(run)


def _docx_response(db: Session, run: DraftRun, template: bytes | None = None) -> Response:
    try:
        content = edits_svc.export_document(db, run, template).data
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    filename = f"draft-minutes-{run.id.hex[:8]}.docx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content, media_type=DOCX_MEDIA_TYPE, headers=headers)


@router.get("/{run_id}/document.docx", response_class=Response)
def download_document(run_id: uuid.UUID, db: DB) -> Response:
    """The draft as Word, with clarification questions as comments. Each download is stored."""
    return _docx_response(db, _run(db, run_id))


@router.post("/{run_id}/document", response_class=Response)
async def download_document_with_template(
    run_id: uuid.UUID,
    db: DB,
    template: Annotated[UploadFile, File(description="Word template (.docx)")],
) -> Response:
    """The draft built into your Word template, at a {{MINUTES}} paragraph if present."""
    data = await _read_limited(template, "template")
    return _docx_response(db, _run(db, run_id), data)


async def _read_limited(file: UploadFile, what: str) -> bytes:
    data = await file.read(settings.minutes_max_upload_bytes + 1)
    if len(data) > settings.minutes_max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"{what} is too large")
    return data


@router.post("/{run_id}/edited-document", status_code=status.HTTP_201_CREATED)
async def upload_edited_document(
    run_id: uuid.UUID,
    db: DB,
    llm: OptionalLLM,
    tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="The edited minutes (.docx)")],
) -> EditedDocumentOut:
    """Upload the minutes as edited in Word and compare them with the downloaded draft.

    If an LLM is configured, the edits are then explained after the response; poll
    GET /api/drafts/{id}/edited-document until classification_status is completed or failed.
    """
    run = _run(db, run_id)
    data = await _read_limited(file, file.filename or "the file")
    try:
        document = edits_svc.upload_edited(db, run, file.filename or "edited.docx", data)
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    if llm is not None and edits_svc.request_classification(db, document):
        amendments_svc.request_proposals(db, document)
        tasks.add_task(amendments_svc.learn_in_background, db.get_bind(), document.id, llm)
    return EditedDocumentOut.of(document)


@router.post("/{run_id}/edited-document/classify", status_code=status.HTTP_202_ACCEPTED)
def classify_edits(
    run_id: uuid.UUID, db: DB, llm: LLM, tasks: BackgroundTasks
) -> EditedDocumentOut:
    """Explain the latest edited copy's changes and propose rule changes again.

    If the edits were explained and only the proposals failed, only those are redone.
    """
    document = _edited(db, run_id)
    found = document.amendments
    if found is not None and found.applied_version_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "the rule changes were already applied")
    assert document.comparison is not None
    explained = document.comparison.classification_status == ClassificationStatus.COMPLETED
    if explained and found is not None and found.status == ClassificationStatus.FAILED:
        if not amendments_svc.request_proposals(db, document):
            raise HTTPException(status.HTTP_409_CONFLICT, "rule changes are already being written")
        tasks.add_task(
            amendments_svc.learn_in_background, db.get_bind(), document.id, llm, explain=False
        )
        return EditedDocumentOut.of(document)
    if not edits_svc.request_classification(db, document):
        raise HTTPException(status.HTTP_409_CONFLICT, "the edits are already being explained")
    amendments_svc.request_proposals(db, document)
    tasks.add_task(amendments_svc.learn_in_background, db.get_bind(), document.id, llm)
    return EditedDocumentOut.of(document)


@router.patch("/{run_id}/amendments/{proposal_id}")
def update_amendment(
    run_id: uuid.UUID, proposal_id: uuid.UUID, body: ProposalUpdate, db: DB
) -> AmendmentProposalOut:
    """Accept, reject or defer a proposed rule change, or reword it."""
    found = _edited(db, run_id).amendments
    proposal = next((p for p in found.proposals if p.id == proposal_id), None) if found else None
    if found is None or proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such proposed change")
    try:
        amendments_svc.update_proposal(db, proposal, status=body.status, text=body.text, by=body.by)
    except amendments_svc.AmendmentStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return AmendmentProposalOut.of(proposal, amendments_svc.current_rules(found))


@router.post("/{run_id}/amendments/apply")
def apply_amendments(
    run_id: uuid.UUID, db: DB, body: ApplyAmendments | None = None
) -> EditedDocumentOut:
    """Create the next profile version with the accepted changes and make it active."""
    document = _edited(db, run_id)
    try:
        amendments_svc.apply(db, document, by=body.by if body else None)
    except amendments_svc.AmendmentStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except profile_svc.FloorViolationError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"floor_violations": e.violations}
        ) from e
    except AmendmentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return EditedDocumentOut.of(document)


@router.get("/{run_id}/edited-document")
def get_edited_document(run_id: uuid.UUID, db: DB) -> EditedDocumentOut:
    """The latest edited copy, its comparison with the draft and the proposed rule changes."""
    return EditedDocumentOut.of(_edited(db, run_id))


def _edited(db: Session, run_id: uuid.UUID) -> EditedDocument:
    document = edits_svc.latest_edited(_run(db, run_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no edited minutes uploaded yet")
    return document
