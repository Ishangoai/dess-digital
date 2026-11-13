import pytest
from sqlalchemy.orm import Session

from app.minutes.profile_content import ProfileContent, ProvisionKind
from app.models.profile import ProfileVersionStatus, VersionOrigin
from app.services import profile as svc

Status = ProfileVersionStatus


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


def test_api_version_cannot_change_hard_floors(
    db: Session, profile_content: ProfileContent
) -> None:
    profile = svc.seed_profile(db, profile_content, slug="std", confirm_version=True).profile

    with pytest.raises(svc.FloorViolationError, match="hard_floors"):
        svc.create_version(
            db,
            profile,
            edited(profile_content, hard_floors=["Anything goes."]),
            origin=VersionOrigin.API,
        )


def test_api_version_cannot_drop_evidential_fundamental(
    db: Session, profile_content: ProfileContent
) -> None:
    profile = svc.seed_profile(db, profile_content, slug="std", confirm_version=True).profile
    data = profile_content.model_dump(mode="json")
    data["minuting_policy"][3]["provisions"] = []  # drops mp4-no-silent-approval

    with pytest.raises(svc.FloorViolationError) as exc:
        svc.create_version(
            db, profile, ProfileContent.model_validate(data), origin=VersionOrigin.API
        )
    assert exc.value.violations == ["evidential fundamental 'mp4-no-silent-approval' was removed"]


def test_api_version_may_change_preferences(db: Session, profile_content: ProfileContent) -> None:
    profile = svc.seed_profile(db, profile_content, slug="std", confirm_version=True).profile
    data = profile_content.model_dump(mode="json")
    data["writing_style"][3]["provisions"][0]["text"] = "Name action owners by full name."
    child = ProfileContent.model_validate(data)

    version = svc.create_version(db, profile, child, origin=VersionOrigin.API)

    assert version.version_number == 2
    assert version.status == Status.PROPOSED
    assert child.provisions_of_kind(ProvisionKind.PREFERENCE)["ws4-names-for-actions"].text == (
        "Name action owners by full name."
    )


def test_duplicate_slug(db: Session) -> None:
    svc.create_profile(db, slug="board", name="Board")
    with pytest.raises(svc.DuplicateProfileError):
        svc.create_profile(db, slug="board", name="Board again")


def test_based_on_links_profiles(db: Session) -> None:
    svc.create_profile(db, slug="std", name="Standard")
    child = svc.create_profile(db, slug="audit", name="Audit", based_on_slug="std")
    assert child.based_on is not None and child.based_on.slug == "std"
