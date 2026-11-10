"""Draft minutes API. Mounted only when MINUTES_ROUTES=true (the API has no auth yet)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.llm import LLMClient, get_llm_client
from app.minutes.evidence import MeetingInfo, SourceRole
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import EvidenceMap
from app.models.draft import DraftRun, DraftStatus
from app.schemas.draft import DraftRunOut, DraftRunSummary, MappingReview
from app.services import draft as svc

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
) -> DraftRunOut:
    """Upload the evidence and map it to the agenda. With auto_confirm_mapping, also draft."""
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
        )
        if auto_confirm_mapping and run.status == DraftStatus.AWAITING_MAPPING_REVIEW:
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
