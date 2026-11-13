import json

import pytest
from pydantic import ValidationError

from app.minutes.profile_content import (
    SCHEMA_PATH,
    ProfileContent,
    ProvisionKind,
    content_hash,
    export_json_schema,
    render_profile,
)


def as_dict(content: ProfileContent) -> dict:
    return content.model_dump(mode="json")


def test_fixture_profile_is_valid(profile_content: ProfileContent) -> None:
    assert [d.code for d in profile_content.minuting_policy][0] == "MP1"
    assert len(profile_content.dimensions()) == 15
    assert set(profile_content.provisions_of_kind(ProvisionKind.EVIDENTIAL_FUNDAMENTAL)) == {
        "mp1-evidence-only",
        "mp4-no-silent-approval",
    }


def test_missing_dimension_is_rejected(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["minuting_policy"] = data["minuting_policy"][:-1]
    with pytest.raises(ValidationError, match="expected dimensions"):
        ProfileContent.model_validate(data)


def test_dimensions_must_be_in_order(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["writing_style"][0], data["writing_style"][1] = (
        data["writing_style"][1],
        data["writing_style"][0],
    )
    with pytest.raises(ValidationError, match="expected dimensions"):
        ProfileContent.model_validate(data)


def test_unknown_fields_are_rejected(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["presentation"]["colour"] = "blue"
    with pytest.raises(ValidationError):
        ProfileContent.model_validate(data)


def test_duplicate_provision_ids_are_rejected(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["writing_style"][0]["provisions"] = [
        {"id": "mp1-evidence-only", "kind": "preference", "text": "dup"}
    ]
    with pytest.raises(ValidationError, match="duplicate provision ids"):
        ProfileContent.model_validate(data)


def test_hard_floors_required(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["hard_floors"] = []
    with pytest.raises(ValidationError):
        ProfileContent.model_validate(data)


def test_content_hash_is_stable_and_content_sensitive(profile_content: ProfileContent) -> None:
    same = ProfileContent.model_validate(as_dict(profile_content))
    assert content_hash(same) == content_hash(profile_content)
    changed = profile_content.model_copy(update={"name": "Other"})
    assert content_hash(changed) != content_hash(profile_content)


def test_committed_json_schema_matches_model() -> None:
    """Regenerate with: uv run python -m app.minutes.profile_content --write"""
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == export_json_schema()


def test_render_profile_includes_floors_and_dimensions(profile_content: ProfileContent) -> None:
    text = render_profile(profile_content)
    assert "## Hard floors" in text
    assert "Do not invent facts" in text
    assert "### MP4 Outcomes" in text
    assert "[evidential_fundamental; dess_standard] Never infer approval" in text
    assert "### WS6 Presentation" in text
