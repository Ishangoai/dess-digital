"""Minutes Profile API. Mounted only when MINUTES_ROUTES=true (the API has no auth yet)."""

import uuid as _uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm import LLMClient
from app.llm.factory import get_llm_client
from app.minutes.profile_content import export_json_schema
from app.models.amendment import ProfileAmendmentSet
from app.models.profile import MinutesProfile, MinutesProfileVersion, VersionOrigin
from app.schemas.amendment import (
    AmendmentSetCreate,
    AmendmentSetOut,
    ApplySetRequest,
    ProposalOut,
    ProposalUpdate,
)
from app.schemas.profile import (
    ProfileCreate,
    ProfileDetail,
    ProfileSummary,
    ProfileVersionCreate,
    ProfileVersionOut,
    StatusChange,
)
from app.services import amendment as amend_svc
from app.services import profile as svc

router = APIRouter(prefix="/profiles", tags=["Minutes profiles"])

DB = Annotated[Session, Depends(get_db)]


def llm_client() -> LLMClient | None:
    try:
        return get_llm_client()
    except Exception:
        return None


LLM = Annotated[LLMClient | None, Depends(llm_client)]


def _profile(db: Session, slug: str) -> MinutesProfile:
    try:
        return svc.get_profile(db, slug)
    except svc.ProfileNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@router.get("")
def list_profiles(db: DB) -> list[ProfileSummary]:
    return [ProfileSummary.of(p) for p in svc.list_profiles(db)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_profile(body: ProfileCreate, db: DB) -> ProfileSummary:
    try:
        profile = svc.create_profile(db, **body.model_dump())
    except svc.ProfileNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except svc.DuplicateProfileError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return ProfileSummary.of(profile)


# Declared before /{slug} so "schema" is not read as a slug.
@router.get("/schema")
def profile_content_schema() -> dict[str, Any]:
    """JSON schema every profile version's content must satisfy."""
    return export_json_schema()


@router.get("/{slug}")
def get_profile(slug: str, db: DB) -> ProfileDetail:
    return ProfileDetail.of(_profile(db, slug))


@router.get("/{slug}/active")
def get_active_version(slug: str, db: DB) -> ProfileVersionOut:
    profile = _profile(db, slug)
    version = svc.active_version(profile)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"profile '{slug}' has no confirmed version")
    return ProfileVersionOut.of(version)


@router.get("/{slug}/versions/{number}")
def get_version(slug: str, number: int, db: DB) -> ProfileVersionOut:
    try:
        return ProfileVersionOut.of(svc.get_version(_profile(db, slug), number))
    except svc.VersionNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@router.post("/{slug}/versions", status_code=status.HTTP_201_CREATED)
def create_version(
    slug: str, body: ProfileVersionCreate, db: DB, admin: bool = False
) -> ProfileVersionOut:
    if not admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Direct profile version creation via YAML is restricted to administrators. "
            "Use the amendment proposal workflow instead, or pass admin=true.",
        )
    profile = _profile(db, slug)
    try:
        version = svc.create_version(
            db,
            profile,
            body.content,
            origin=VersionOrigin.API,
            change_summary=body.change_summary,
            created_by=body.created_by,
            parent_number=body.parent_version,
        )
    except svc.VersionNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except svc.FloorViolationError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"floor_violations": e.violations}
        ) from e
    return ProfileVersionOut.of(version)


@router.post("/{slug}/versions/{number}/status")
def change_version_status(slug: str, number: int, body: StatusChange, db: DB) -> ProfileVersionOut:
    try:
        version = svc.get_version(_profile(db, slug), number)
        version = svc.change_status(db, version, body.status, by=body.by)
    except svc.VersionNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except svc.InvalidTransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return ProfileVersionOut.of(version)


# ── Amendment sets ─────────────────────────────────────────────────────────────


@router.post("/{slug}/amendment-sets", status_code=status.HTTP_201_CREATED)
def create_amendment_set(
    slug: str, body: AmendmentSetCreate, db: DB, llm: LLM = None
) -> AmendmentSetOut:
    """Create a new amendment set (batch of proposals) for a specific profile version."""
    profile = _profile(db, slug)
    version = db.scalar(
        select(MinutesProfileVersion).where(MinutesProfileVersion.id == body.profile_version_id)
    )
    if version is None or version.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile version not found")
    try:
        aset = amend_svc.create_amendment_set(
            db,
            version,
            origin=body.origin,
            title=body.title,
            created_by=body.created_by,
            proposals=[p.model_dump() for p in body.proposals],
            llm=llm,
        )
    except amend_svc.AmendmentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return AmendmentSetOut.of(aset)


@router.get("/{slug}/amendment-sets")
def list_amendment_sets(
    slug: str, db: DB, version_id: _uuid.UUID | None = None
) -> list[AmendmentSetOut]:
    """List all amendment sets for a profile (optionally filtered by version UUID)."""
    profile = _profile(db, slug)
    q = (
        select(ProfileAmendmentSet)
        .join(MinutesProfileVersion)
        .where(MinutesProfileVersion.profile_id == profile.id)
    )
    if version_id is not None:
        q = q.where(ProfileAmendmentSet.profile_version_id == version_id)
    q = q.order_by(ProfileAmendmentSet.created_at.desc())
    sets = list(db.scalars(q))
    return [AmendmentSetOut.of(s) for s in sets]


@router.get("/{slug}/amendment-sets/{set_id}")
def get_amendment_set(slug: str, set_id: _uuid.UUID, db: DB) -> AmendmentSetOut:
    """Retrieve a single amendment set by its UUID."""
    _profile(db, slug)
    try:
        aset = amend_svc.get_amendment_set(db, set_id)
    except amend_svc.AmendmentSetNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return AmendmentSetOut.of(aset)


@router.patch("/{slug}/amendment-sets/{set_id}/proposals/{proposal_id}")
def update_proposal(
    slug: str,
    set_id: _uuid.UUID,
    proposal_id: _uuid.UUID,
    body: ProposalUpdate,
    db: DB,
) -> ProposalOut:
    """Accept, reject, defer, or reword a single proposal within an amendment set."""
    _profile(db, slug)
    try:
        aset = amend_svc.get_amendment_set(db, set_id)
    except amend_svc.AmendmentSetNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    proposal = next((p for p in aset.proposals if p.id == proposal_id), None)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")

    try:
        proposal = amend_svc.update_proposal(
            db,
            proposal,
            status=body.status,
            proposed_text=body.proposed_text,
            decided_by=body.decided_by,
        )
    except amend_svc.AmendmentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return ProposalOut.of(proposal)


@router.post("/{slug}/amendment-sets/{set_id}/apply", status_code=status.HTTP_201_CREATED)
def apply_amendment_set(
    slug: str, set_id: _uuid.UUID, body: ApplySetRequest, db: DB
) -> ProfileVersionOut:
    """
    Apply all accepted proposals in an amendment set
    to produce a new confirmed profile version.
    """
    _profile(db, slug)
    try:
        aset = amend_svc.get_amendment_set(db, set_id)
        new_version = amend_svc.apply_amendment_set(db, aset, confirmed_by=body.confirmed_by)
    except amend_svc.AmendmentSetNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except (amend_svc.AmendmentError, svc.FloorViolationError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return ProfileVersionOut.of(new_version)
