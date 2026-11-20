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
from app.minutes.docx_export import DOCX_MEDIA_TYPE
from app.minutes.evidence import MeetingInfo, SourceRole
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import EvidenceMap
from app.minutes.roundtrip import WrongDraftError
from app.models.draft import DraftRun, DraftStatus
from app.models.edits import EditedDocument
from app.schemas.draft import DraftRunOut, DraftRunSummary, LLMCallDetail, MappingReview
from app.schemas.edits import EditedSummary, EditReview
from app.schemas.feedback import FeedbackIn, FeedbackOut
from app.services import draft as svc
from app.services import edit_classify
from app.services import edits as edits_svc
from app.services import feedback as feedback_svc

router = APIRouter(prefix="/drafts", tags=["Draft minutes"])

DB = Annotated[Session, Depends(get_db)]


def llm_client() -> LLMClient:
    try:
        return get_llm_client()
    except ValueError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LLM not configured: {e}") from e


LLM = Annotated[LLMClient, Depends(llm_client)]


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
    """Every download is stored exactly, as the original an edited copy is compared with."""
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
    """The draft as Word, with clarification questions as comments."""
    return _docx_response(db, _run(db, run_id))


@router.post("/{run_id}/document", response_class=Response)
async def download_document_with_template(
    run_id: uuid.UUID,
    db: DB,
    template: Annotated[UploadFile, File(description="Word template (.docx)")],
) -> Response:
    """The draft built into your Word template, at a {{MINUTES}} paragraph if present."""
    data = await template.read(settings.minutes_max_upload_bytes + 1)
    if len(data) > settings.minutes_max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "template is too large")
    return _docx_response(db, _run(db, run_id), data)


@router.post("/{run_id}/feedback", status_code=status.HTTP_201_CREATED)
def add_feedback(run_id: uuid.UUID, body: FeedbackIn, db: DB) -> FeedbackOut:
    """Approve the draft or request a revision (with a reason)."""
    run = _run(db, run_id)
    try:
        vote = feedback_svc.add_feedback(db, run, body.verdict, body.reason, body.by)
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except svc.InvalidInputError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return FeedbackOut.model_validate(vote)


@router.post("/{run_id}/final", status_code=status.HTTP_201_CREATED)
async def upload_final(
    run_id: uuid.UUID,
    db: DB,
    llm: LLM,
    tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="The edited Word copy of this draft (.docx)")],
    by: Annotated[str | None, Form(max_length=255)] = None,
) -> FeedbackOut:
    """Store the professional's edited Word copy and line it up with the exact original.

    Its edits are then classified in the background (MINUTES_AUTO_CLASSIFY).
    """
    run = _run(db, run_id)
    data = await file.read(settings.minutes_max_upload_bytes + 1)
    if len(data) > settings.minutes_max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file is too large")
    try:
        edited, feedback = edits_svc.upload_edited(db, run, file.filename or "final.docx", data, by)
    except svc.InvalidStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    except WrongDraftError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    if settings.minutes_auto_classify:
        tasks.add_task(edit_classify.classify_in_background, db.get_bind(), edited.id, llm)
    return FeedbackOut.model_validate(feedback)


@router.get("/{run_id}/feedback")
def list_feedback(run_id: uuid.UUID, db: DB) -> list[FeedbackOut]:
    """All feedback on this draft, oldest first."""
    votes = feedback_svc.votes_for(db, _run(db, run_id))
    return [FeedbackOut.model_validate(v) for v in votes]


@router.get("/{run_id}/edits")
def list_edits(run_id: uuid.UUID, db: DB) -> list[EditedSummary]:
    """Edited copies uploaded for this draft, newest first."""
    return [EditedSummary.of(e) for e in edits_svc.list_edited(db, _run(db, run_id))]


@router.get("/{run_id}/edits/{edited_id}")
def get_edit(run_id: uuid.UUID, edited_id: uuid.UUID, db: DB) -> EditReview:
    """Paragraph by paragraph: what changed, with word-level differences and any labels."""
    return EditReview.of(_edited(db, run_id, edited_id))


@router.post("/{run_id}/edits/{edited_id}/classify")
def classify_edit(
    run_id: uuid.UUID,
    edited_id: uuid.UUID,
    db: DB,
    llm: Annotated[LLMClient, Depends(llm_client)],
) -> EditReview:
    """Label each edit by kind, dimension and cause; repeated edits are grouped."""
    edited = _edited(db, run_id, edited_id)
    return EditReview.of(edit_classify.classify(db, llm, edited.run, edited))


def _edited(db: Session, run_id: uuid.UUID, edited_id: uuid.UUID) -> EditedDocument:
    try:
        return edits_svc.get_edited(db, _run(db, run_id), edited_id)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
