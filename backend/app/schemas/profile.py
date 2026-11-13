from datetime import datetime

from pydantic import BaseModel, Field

from app.minutes.profile_content import ProfileContent
from app.models.profile import (
    MinutesProfile,
    MinutesProfileVersion,
    ProfileVersionStatus,
    VersionOrigin,
)
from app.services.profile import active_version, latest_version

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


class ProfileCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    body_name: str | None = Field(default=None, max_length=255)
    based_on_slug: str | None = None


class ProfileVersionCreate(BaseModel):
    content: ProfileContent
    change_summary: str | None = None
    parent_version: int | None = Field(default=None, ge=1)
    created_by: str | None = None


class StatusChange(BaseModel):
    status: ProfileVersionStatus
    by: str | None = None


class VersionSummary(BaseModel):
    version_number: int
    status: ProfileVersionStatus
    origin: VersionOrigin
    content_sha256: str
    change_summary: str | None
    created_by: str | None
    created_at: datetime
    confirmed_at: datetime | None

    @classmethod
    def of(cls, v: MinutesProfileVersion) -> "VersionSummary":
        return cls(
            version_number=v.version_number,
            status=v.status,
            origin=v.origin,
            content_sha256=v.content_sha256,
            change_summary=v.change_summary,
            created_by=v.created_by,
            created_at=v.created_at,
            confirmed_at=v.confirmed_at,
        )


class ProfileVersionOut(VersionSummary):
    profile_slug: str
    parent_version: int | None
    reviewed_at: datetime | None
    confirmed_by: str | None
    content_schema_version: int
    content: ProfileContent

    @classmethod
    def of(cls, v: MinutesProfileVersion) -> "ProfileVersionOut":
        return cls(
            **VersionSummary.of(v).model_dump(),
            profile_slug=v.profile.slug,
            parent_version=v.parent.version_number if v.parent else None,
            reviewed_at=v.reviewed_at,
            confirmed_by=v.confirmed_by,
            content_schema_version=v.content_schema_version,
            content=ProfileContent.model_validate(v.content),
        )


class ProfileSummary(BaseModel):
    slug: str
    name: str
    description: str | None
    body_name: str | None
    based_on_slug: str | None
    active_version: int | None
    latest_version: int | None

    @classmethod
    def of(cls, p: MinutesProfile) -> "ProfileSummary":
        active, latest = active_version(p), latest_version(p)
        return cls(
            slug=p.slug,
            name=p.name,
            description=p.description,
            body_name=p.body_name,
            based_on_slug=p.based_on.slug if p.based_on else None,
            active_version=active.version_number if active else None,
            latest_version=latest.version_number if latest else None,
        )


class ProfileDetail(ProfileSummary):
    versions: list[VersionSummary]

    @classmethod
    def of(cls, p: MinutesProfile) -> "ProfileDetail":
        return cls(
            **ProfileSummary.of(p).model_dump(),
            versions=[VersionSummary.of(v) for v in p.versions],
        )
