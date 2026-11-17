from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session

from app.minutes.profile_content import ProfileContent
from app.models.profile import ProfileVersionStatus, VersionOrigin
from app.services import profile as svc

Status = ProfileVersionStatus
FIXTURES = Path(__file__).parent / "fixtures" / "minutes"


def edited(content: ProfileContent, **changes: object) -> ProfileContent:
    data = content.model_dump(mode="json") | changes
    return ProfileContent.model_validate(data)


def test_seed_creates_confirmed_version(db: Session, profile_content: ProfileContent) -> None:
    result = svc.seed_profile(db, profile_content, slug="std", confirm_version=True)

    assert result.created
    assert result.profile.name == "Test Standard Profile"
    assert result.version.version_number == 1
    assert result.version.status == Status.CONFIRMED
    assert result.version.confirmed_by == "seed"
    assert svc.active_version(result.profile) == result.version


def test_seed_is_idempotent(db: Session, profile_content: ProfileContent) -> None:
    svc.seed_profile(db, profile_content, slug="std")
    again = svc.seed_profile(db, profile_content, slug="std")

    assert not again.created
    assert [v.version_number for v in again.profile.versions] == [1]


def test_seed_with_changed_content_adds_version(
    db: Session, profile_content: ProfileContent
) -> None:
    svc.seed_profile(db, profile_content, slug="std", confirm_version=True)
    result = svc.seed_profile(
        db, edited(profile_content, description="v2"), slug="std", confirm_version=True
    )

    assert result.created
    assert result.version.version_number == 2
    assert result.version.parent is not None
    assert result.version.parent.version_number == 1
    assert svc.active_version(result.profile) == result.version


def test_active_version_is_highest_confirmed(db: Session, profile_content: ProfileContent) -> None:
    profile = svc.seed_profile(db, profile_content, slug="std", confirm_version=True).profile
    svc.create_version(
        db, profile, edited(profile_content, description="draft"), origin=VersionOrigin.API
    )

    latest = svc.latest_version(profile)
    assert latest is not None and latest.version_number == 2
    active = svc.active_version(profile)
    assert active is not None and active.version_number == 1


def test_no_active_version_until_confirmed(db: Session, profile_content: ProfileContent) -> None:
    profile = svc.seed_profile(db, profile_content, slug="std").profile
    assert svc.active_version(profile) is None


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ([Status.REVIEWED, Status.CONFIRMED], True),
        ([Status.WITHDRAWN], True),
        ([Status.REVIEWED, Status.WITHDRAWN], True),
        ([Status.CONFIRMED], False),  # must be reviewed first
        ([Status.REVIEWED, Status.CONFIRMED, Status.WITHDRAWN], False),  # confirmed is final
        ([Status.WITHDRAWN, Status.REVIEWED], False),  # withdrawn is final
    ],
)
def test_status_transitions(
    db: Session, profile_content: ProfileContent, path: list[Status], allowed: bool
) -> None:
    version = svc.seed_profile(db, profile_content, slug="std").version

    def walk() -> None:
        for step in path:
            svc.change_status(db, version, step, by="tester")

    if allowed:
        walk()
        assert version.status == path[-1]
    else:
        with pytest.raises(svc.InvalidTransitionError):
            walk()


def test_api_version_with_new_logic_is_proposed(
    db: Session, profile_content: ProfileContent
) -> None:
    profile = svc.seed_profile(db, profile_content, slug="std", confirm_version=True).profile
    child = edited(profile_content, logic="# Test Standard Profile\n\nName owners by role.")

    version = svc.create_version(db, profile, child, origin=VersionOrigin.API)

    assert version.version_number == 2
    assert version.status == Status.PROPOSED
    assert svc.version_content(version).logic.endswith("Name owners by role.")


def test_seeding_markdown_over_a_schema_1_version(
    db: Session, profile_content: ProfileContent
) -> None:
    """The first deploy after the move to markdown: v1 is old structured content."""
    old = yaml.safe_load((FIXTURES / "profile_v1.yaml").read_text(encoding="utf-8"))
    profile = svc.seed_profile(db, profile_content, slug="std", confirm_version=True).profile
    v1 = svc.latest_version(profile)
    assert v1 is not None
    v1.content, v1.content_sha256 = old, "sha-of-the-old-yaml"  # as stored before the change
    db.commit()

    result = svc.seed_profile(db, profile_content, slug="std", confirm_version=True)

    assert result.created and result.version.version_number == 2
    assert svc.active_version(result.profile) == result.version
    assert "### MP4 Outcomes" in svc.version_content(v1).logic  # the old version still reads


def test_duplicate_slug(db: Session) -> None:
    svc.create_profile(db, slug="board", name="Board")
    with pytest.raises(svc.DuplicateProfileError):
        svc.create_profile(db, slug="board", name="Board again")


def test_based_on_links_profiles(db: Session) -> None:
    svc.create_profile(db, slug="std", name="Standard")
    child = svc.create_profile(db, slug="audit", name="Audit", based_on_slug="std")
    assert child.based_on is not None and child.based_on.slug == "std"
