"""Minutes Profile versioning rules.

- Version content is immutable; a change is a new version (numbered 1, 2, 3 ... per profile).
- Status lifecycle: proposed -> reviewed -> confirmed, or proposed/reviewed -> withdrawn.
- The active version is the confirmed version with the highest number (derived, not stored).
- Non-seed versions may not change the hard floors or evidential fundamentals of their parent.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.minutes.profile_content import (
    PROFILE_SCHEMA_VERSION,
    ProfileContent,
    ProvisionKind,
    content_hash,
)
from app.models.profile import (
    MinutesProfile,
    MinutesProfileVersion,
    ProfileVersionStatus,
    VersionOrigin,
    utcnow,
)

Status = ProfileVersionStatus

ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.PROPOSED: {Status.REVIEWED, Status.WITHDRAWN},
    Status.REVIEWED: {Status.CONFIRMED, Status.WITHDRAWN},
    Status.CONFIRMED: set(),
    Status.WITHDRAWN: set(),
}


class ProfileError(Exception):
    """Base class for profile service errors."""


class ProfileNotFoundError(ProfileError):
    pass


class VersionNotFoundError(ProfileError):
    pass


class DuplicateProfileError(ProfileError):
    pass


class InvalidTransitionError(ProfileError):
    pass


class FloorViolationError(ProfileError):
    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


# --- profiles ------------------------------------------------------------------------------


def create_profile(
    db: Session,
    *,
    slug: str,
    name: str,
    description: str | None = None,
    body_name: str | None = None,
    based_on_slug: str | None = None,
) -> MinutesProfile:
    based_on = get_profile(db, based_on_slug) if based_on_slug else None
    profile = MinutesProfile(
        slug=slug,
        name=name,
        description=description,
        body_name=body_name,
        based_on_profile_id=based_on.id if based_on else None,
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise DuplicateProfileError(f"profile '{slug}' already exists") from e
    db.refresh(profile)
    return profile


def get_profile(db: Session, slug: str) -> MinutesProfile:
    profile = db.scalar(select(MinutesProfile).where(MinutesProfile.slug == slug))
    if profile is None:
        raise ProfileNotFoundError(f"profile '{slug}' not found")
    return profile


def list_profiles(db: Session) -> list[MinutesProfile]:
    return list(db.scalars(select(MinutesProfile).order_by(MinutesProfile.slug)))


# --- versions ------------------------------------------------------------------------------


def latest_version(profile: MinutesProfile) -> MinutesProfileVersion | None:
    return profile.versions[-1] if profile.versions else None


def active_version(profile: MinutesProfile) -> MinutesProfileVersion | None:
    confirmed = [v for v in profile.versions if v.status == Status.CONFIRMED]
    return confirmed[-1] if confirmed else None


def get_version(profile: MinutesProfile, number: int) -> MinutesProfileVersion:
    for v in profile.versions:
        if v.version_number == number:
            return v
    raise VersionNotFoundError(f"profile '{profile.slug}' has no version {number}")


def version_content(version: MinutesProfileVersion) -> ProfileContent:
    return ProfileContent.model_validate(version.content)


def check_floors(parent: ProfileContent, child: ProfileContent) -> list[str]:
    """Hard floors and evidential fundamentals must be carried over unchanged."""
    violations: list[str] = []
    if child.hard_floors != parent.hard_floors:
        violations.append("hard_floors differ from the parent version")
    parent_fixed = parent.provisions_of_kind(ProvisionKind.EVIDENTIAL_FUNDAMENTAL)
    child_fixed = child.provisions_of_kind(ProvisionKind.EVIDENTIAL_FUNDAMENTAL)
    for pid, provision in parent_fixed.items():
        if pid not in child_fixed:
            violations.append(f"evidential fundamental '{pid}' was removed")
        elif child_fixed[pid] != provision:
            violations.append(f"evidential fundamental '{pid}' was changed")
    return violations


def create_version(
    db: Session,
    profile: MinutesProfile,
    content: ProfileContent,
    *,
    origin: VersionOrigin,
    change_summary: str | None = None,
    created_by: str | None = None,
    parent_number: int | None = None,
) -> MinutesProfileVersion:
    """Add a new `proposed` version. Parent defaults to the active (else latest) version."""
    if parent_number is not None:
        parent = get_version(profile, parent_number)
    else:
        parent = active_version(profile) or latest_version(profile)

    if parent is not None and origin != VersionOrigin.SEED:
        violations = check_floors(version_content(parent), content)
        if violations:
            raise FloorViolationError(violations)

    current_max = db.scalar(
        select(func.max(MinutesProfileVersion.version_number)).where(
            MinutesProfileVersion.profile_id == profile.id
        )
    )
    version = MinutesProfileVersion(
        profile_id=profile.id,
        version_number=(current_max or 0) + 1,
        status=Status.PROPOSED,
        content=content.model_dump(mode="json"),
        content_schema_version=PROFILE_SCHEMA_VERSION,
        content_sha256=content_hash(content),
        origin=origin,
        parent_version_id=parent.id if parent else None,
        change_summary=change_summary,
        created_by=created_by,
    )
    db.add(version)
    db.commit()
    db.refresh(profile)
    return version


def change_status(
    db: Session, version: MinutesProfileVersion, new_status: Status, *, by: str | None = None
) -> MinutesProfileVersion:
    current = Status(version.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"cannot move a {current} version to {new_status}")
    now: datetime = utcnow()
    version.status = new_status
    if new_status == Status.REVIEWED:
        version.reviewed_at = now
    elif new_status == Status.CONFIRMED:
        version.confirmed_at = now
        version.confirmed_by = by
    elif new_status == Status.WITHDRAWN:
        version.withdrawn_at = now
    db.commit()
    db.refresh(version)
    return version


def confirm(db: Session, version: MinutesProfileVersion, *, by: str | None = None) -> None:
    """Walk a version through review to confirmed (used by seeding)."""
    if version.status == Status.PROPOSED:
        change_status(db, version, Status.REVIEWED, by=by)
    if version.status == Status.REVIEWED:
        change_status(db, version, Status.CONFIRMED, by=by)


# --- seeding -------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedResult:
    profile: MinutesProfile
    version: MinutesProfileVersion
    created: bool  # False when the latest version already had identical content


def seed_profile(
    db: Session,
    content: ProfileContent,
    *,
    slug: str,
    confirm_version: bool = False,
    by: str | None = "seed",
) -> SeedResult:
    """Idempotently load profile content: a new version only if the content changed."""
    try:
        profile = get_profile(db, slug)
    except ProfileNotFoundError:
        profile = create_profile(db, slug=slug, name=content.name, description=content.description)

    latest = latest_version(profile)
    if latest is not None and latest.content_sha256 == content_hash(content):
        version, created = latest, False
    else:
        version = create_version(
            db,
            profile,
            content,
            origin=VersionOrigin.SEED,
            change_summary="Loaded from profile file",
            created_by=by,
        )
        created = True

    if confirm_version:
        confirm(db, version, by=by)
    return SeedResult(profile=profile, version=version, created=created)
