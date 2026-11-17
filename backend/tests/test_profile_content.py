import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.minutes.profile_content import (
    DEFAULT_PROFILE_PATH,
    SCHEMA_PATH,
    ProfileContent,
    content_hash,
    export_json_schema,
    load_profile_file,
)

FIXTURES = Path(__file__).parent / "fixtures" / "minutes"


def as_dict(content: ProfileContent) -> dict:
    return content.model_dump(mode="json")


def test_md_profile_takes_its_name_from_the_first_heading(profile_content: ProfileContent) -> None:
    assert profile_content.name == "Test Standard Profile"
    assert profile_content.logic.startswith("# Test Standard Profile")
    assert "### MP4 Outcomes" in profile_content.logic
    assert profile_content.presentation.status_label == "Draft"  # Word defaults


def test_bundled_dess_profile_loads() -> None:
    content = load_profile_file(DEFAULT_PROFILE_PATH)
    assert content.name == "DESS Standard Minutes Profile"
    assert "# Part A: Professional Standards" in content.logic
    assert "# Part B: Operational AI Logic" in content.logic


def test_logic_is_required(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["logic"] = ""
    with pytest.raises(ValidationError):
        ProfileContent.model_validate(data)


def test_unknown_fields_are_rejected(profile_content: ProfileContent) -> None:
    data = as_dict(profile_content)
    data["presentation"]["colour"] = "blue"
    with pytest.raises(ValidationError):
        ProfileContent.model_validate(data)


def test_unsupported_file_type(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("name: x", encoding="utf-8")
    with pytest.raises(ValueError, match="use .md or .json"):
        load_profile_file(path)


def test_schema_1_profiles_are_read_as_one_markdown_text() -> None:
    """Versions stored before the move to markdown still load (e.g. for old drafts)."""
    data = yaml.safe_load((FIXTURES / "profile_v1.yaml").read_text(encoding="utf-8"))

    content = ProfileContent.model_validate(data)

    assert content.name == "Test Standard Profile"
    assert content.logic.startswith("Produce a first draft of minutes")  # the old core text
    assert "- Do not invent facts, decisions or reasons." in content.logic
    assert "### MP4 Outcomes" in content.logic
    assert "- Never infer approval from silence or an agenda label." in content.logic
    assert "## Stage guidance: questions" in content.logic
    assert content.presentation.status_label == "Draft"


def test_content_hash_is_stable_and_content_sensitive(profile_content: ProfileContent) -> None:
    same = ProfileContent.model_validate(as_dict(profile_content))
    assert content_hash(same) == content_hash(profile_content)
    changed = profile_content.model_copy(update={"logic": "Other text"})
    assert content_hash(changed) != content_hash(profile_content)


def test_committed_json_schema_matches_model() -> None:
    """Regenerate with: uv run python -m app.minutes.profile_content --write"""
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == export_json_schema()
