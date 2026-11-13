"""Minutes Profile API. Mounted only when MINUTES_ROUTES=true (the API has no auth yet)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.minutes.profile_content import export_json_schema
from app.models.profile import MinutesProfile, VersionOrigin
from app.schemas.profile import (
    ProfileCreate,
    ProfileDetail,
    ProfileSummary,
    ProfileVersionCreate,
    ProfileVersionOut,
    StatusChange,
)
from app.services import profile as svc

router = APIRouter(prefix="/profiles", tags=["Minutes profiles"])

DB = Annotated[Session, Depends(get_db)]


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
def create_version(slug: str, body: ProfileVersionCreate, db: DB) -> ProfileVersionOut:
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
