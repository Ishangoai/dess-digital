"""Minutes Profile content: the minuting logic as markdown, plus Word presentation settings.

Regenerate the committed JSON schema with: uv run python -m app.minutes.profile_content --write
"""

import argparse
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILE_SCHEMA_VERSION = 2
SCHEMA_PATH = Path(__file__).with_name(f"profile_content.v{PROFILE_SCHEMA_VERSION}.schema.json")
# The DESS Standard profile shipped with the app; every deploy seeds it.
DEFAULT_PROFILE_PATH = Path(__file__).parent / "profiles" / "dess_standard.md"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateStyle(StrEnum):
    LONG = "long"  # 4 November 2026
    ORDINAL = "ordinal"  # 4th November 2026
    NUMERIC = "numeric"  # 04/11/2026


class NumberingScheme(StrEnum):
    AGENDA = "agenda"  # reuse the agenda's item numbers
    SEQUENTIAL = "sequential"  # 1, 2, 3 in minute order
    MINUTE_REFERENCE = "minute_reference"  # e.g. B/26/01


class ParagraphNumbering(StrEnum):
    NONE = "none"
    ITEM_DECIMAL = "item_decimal"  # 4.1, 4.2 ...


class ActionPresentation(StrEnum):
    INLINE = "inline"
    INLINE_AND_TABLE = "inline_and_table"


class AttendanceLayout(StrEnum):
    PARAGRAPH = "paragraph"
    LIST = "list"


class StyleMap(_Strict):
    """Word style names used in the exported document."""

    title: str = "Title"
    heading: str = "Heading 1"
    body: str = "Normal"
    table: str = "Table Grid"


class PresentationSettings(_Strict):
    date_style: DateStyle = DateStyle.LONG
    title_template: str = "Minutes of a meeting of the {body} of {organisation}"
    status_label: str | None = "Draft"
    numbering: NumberingScheme = NumberingScheme.AGENDA
    minute_reference_prefix: str | None = None
    paragraph_numbering: ParagraphNumbering = ParagraphNumbering.NONE
    action_presentation: ActionPresentation = ActionPresentation.INLINE
    attendance_layout: AttendanceLayout = AttendanceLayout.LIST
    styles: StyleMap = Field(default_factory=StyleMap)
    font_family: str | None = Field(default=None, description="Only used without a template.")
    font_size_pt: float | None = Field(default=None, gt=0)
    comment_author: str = "DESS Minutes"
    comment_initials: str = "DM"


class ProfileContent(_Strict):
    model_config = ConfigDict(extra="forbid", title="MinutesProfileContent")

    schema_version: Literal[2] = 2
    name: str = Field(min_length=1)
    description: str | None = None
    jurisdiction: Literal["UK"] = "UK"
    logic: str = Field(
        min_length=1, description="The full minuting logic in markdown, sent on every LLM call."
    )
    presentation: PresentationSettings = Field(default_factory=PresentationSettings)

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data: Any) -> Any:
        """Read schema 1 profiles (structured dimensions) by joining them into one text."""
        if isinstance(data, dict) and "minuting_policy" in data:
            return _upgrade_v1(data)
        if isinstance(data, dict) and "lessons" in data:  # a field briefly used, now removed
            return {k: v for k, v in data.items() if k != "lessons"}
        return data


def _upgrade_v1(data: dict[str, Any]) -> dict[str, Any]:
    ops = data.get("operational_instructions") or {}
    lines = [ops.get("core", ""), "", "## Hard floors", *[f"- {f}" for f in data["hard_floors"]]]
    for section, key in (
        ("Minuting Policy", "minuting_policy"),
        ("Writing Style", "writing_style"),
    ):
        lines += ["", f"## {section}"]
        for d in data[key]:
            lines += [
                "",
                f"### {d['code']} {d['title']}",
                "",
                d["purpose"],
                "",
                d["default_standard"],
            ]
            for field in ("application", "customisation_scope", "rationale"):
                if d.get(field):
                    lines += ["", d[field]]
            lines += [f"- {p['text']}" for p in d.get("provisions", [])]
    for stage, text in (ops.get("stages") or {}).items():
        if text:
            lines += ["", f"## Stage guidance: {stage}", "", text]
    return {
        "name": data["name"],
        "description": data.get("description"),
        "logic": "\n".join(lines).strip(),
        "presentation": data.get("presentation") or {},
    }


def content_hash(content: ProfileContent) -> str:
    """sha256 of the content, used to skip re-seeding identical profiles."""
    canonical = json.dumps(content.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_profile_file(path: Path) -> ProfileContent:
    """Read a profile: a .md file (its first heading is the name) or full .json content."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".md":
        return ProfileContent(name=markdown_title(text) or path.stem, logic=text)
    if suffix == ".json":
        return ProfileContent.model_validate(json.loads(text))
    raise ValueError(f"unsupported profile file type: {suffix} (use .md or .json)")


def markdown_title(text: str) -> str | None:
    """Text of the first '# ' heading, if any."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or None
    return None


def export_json_schema() -> dict[str, Any]:
    return ProfileContent.model_json_schema()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Profile content JSON schema")
    parser.add_argument("--write", action="store_true", help=f"write {SCHEMA_PATH.name}")
    args = parser.parse_args()
    text = json.dumps(export_json_schema(), indent=2) + "\n"
    if args.write:
        SCHEMA_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {SCHEMA_PATH}")
    else:
        print(text, end="")


if __name__ == "__main__":
    _main()
