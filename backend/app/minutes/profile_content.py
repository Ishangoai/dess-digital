"""Minutes Profile content: Minuting Policy (MP1-MP9), Writing Style (WS1-WS6) and presentation.

Regenerate the committed JSON schema with: uv run python -m app.minutes.profile_content --write
"""

import argparse
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROFILE_SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name(f"profile_content.v{PROFILE_SCHEMA_VERSION}.schema.json")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DimensionCode(StrEnum):
    MP1 = "MP1"  # Meeting and business context
    MP2 = "MP2"  # Information and evidential basis
    MP3 = "MP3"  # Materiality and proportionality
    MP4 = "MP4"  # Outcomes and decisions
    MP5 = "MP5"  # Decision reasoning
    MP6 = "MP6"  # Challenge and oversight
    MP7 = "MP7"  # Actions and delegation
    MP8 = "MP8"  # Governance and procedure
    MP9 = "MP9"  # Boundaries and integrity
    WS1 = "WS1"  # Voice, tense and tone
    WS2 = "WS2"  # Structure and sequence
    WS3 = "WS3"  # Concision, clarity and explanation
    WS4 = "WS4"  # Attribution
    WS5 = "WS5"  # Expression of decisions and actions
    WS6 = "WS6"  # Document conventions and presentation


POLICY_CODES = [c for c in DimensionCode if c.startswith("MP")]
STYLE_CODES = [c for c in DimensionCode if c.startswith("WS")]


class ProvisionKind(StrEnum):
    EVIDENTIAL_FUNDAMENTAL = "evidential_fundamental"  # fixed, cannot be customised
    REQUIREMENT = "requirement"  # legal, regulatory or organisational
    PROFESSIONAL_DEFAULT = "professional_default"
    PREFERENCE = "preference"


class Provenance(StrEnum):
    DESS_STANDARD = "dess_standard"
    INFERRED = "inferred"
    EXPLICIT_REQUIREMENT = "explicit_requirement"
    PROFESSIONAL_PREFERENCE = "professional_preference"


class Provision(_Strict):
    id: str = Field(min_length=1, description="Stable id, unique within the profile.")
    kind: ProvisionKind
    text: str = Field(min_length=1)
    provenance: Provenance = Provenance.DESS_STANDARD
    source_note: str | None = None


class Dimension(_Strict):
    code: DimensionCode
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    default_standard: str = Field(min_length=1, description="The standard this profile applies.")
    application: str | None = Field(default=None, description="How the standard is applied.")
    customisation_scope: str | None = Field(default=None, description="Allowed variations.")
    rationale: str | None = Field(default=None, description="Background; not sent to the model.")
    provisions: list[Provision] = Field(default_factory=list)


class StageGuidance(_Strict):
    """Extra instructions for each pipeline stage."""

    evidence: str | None = None
    policy: str | None = None
    style: str | None = None
    questions: str | None = None
    validation: str | None = None
    presentation: str | None = None


class OperationalInstructions(_Strict):
    core: str = Field(min_length=1, description="Main instructions given to the model.")
    stages: StageGuidance = Field(default_factory=StageGuidance)


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

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    description: str | None = None
    jurisdiction: Literal["UK"] = "UK"
    hard_floors: list[str] = Field(min_length=1, description="Rules no customisation can override.")
    minuting_policy: list[Dimension]
    writing_style: list[Dimension]
    presentation: PresentationSettings = Field(default_factory=PresentationSettings)
    operational_instructions: OperationalInstructions

    @field_validator("minuting_policy")
    @classmethod
    def _policy_codes(cls, dims: list[Dimension]) -> list[Dimension]:
        return _check_codes(dims, POLICY_CODES)

    @field_validator("writing_style")
    @classmethod
    def _style_codes(cls, dims: list[Dimension]) -> list[Dimension]:
        return _check_codes(dims, STYLE_CODES)

    @model_validator(mode="after")
    def _unique_provision_ids(self) -> "ProfileContent":
        ids = [p.id for d in self.dimensions() for p in d.provisions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate provision ids: {', '.join(duplicates)}")
        return self

    def dimensions(self) -> list[Dimension]:
        return [*self.minuting_policy, *self.writing_style]

    def provisions_of_kind(self, kind: ProvisionKind) -> dict[str, Provision]:
        return {p.id: p for d in self.dimensions() for p in d.provisions if p.kind == kind}


def _check_codes(dims: list[Dimension], expected: list[DimensionCode]) -> list[Dimension]:
    codes = [d.code for d in dims]
    if codes != expected:
        raise ValueError(f"expected dimensions {', '.join(expected)} in order, got {codes}")
    return dims


def content_hash(content: ProfileContent) -> str:
    """sha256 of the content, used to skip re-seeding identical profiles."""
    canonical = json.dumps(content.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_profile_file(path: Path) -> ProfileContent:
    """Read a profile from .yaml/.yml/.json."""
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data: Any = yaml.safe_load(raw_text)
    elif path.suffix.lower() == ".json":
        data = json.loads(raw_text)
    else:
        raise ValueError(f"unsupported profile file type: {path.suffix} (use .yaml or .json)")
    return ProfileContent.model_validate(data)


def export_json_schema() -> dict[str, Any]:
    return ProfileContent.model_json_schema()


def render_profile(content: ProfileContent) -> str:
    """Profile as markdown for the model prompt (without rationale)."""
    lines = [f"# Minutes Profile: {content.name}", ""]
    if content.description:
        lines += [content.description, ""]
    lines += ["## Hard floors (never overridden)", *[f"- {f}" for f in content.hard_floors], ""]
    for section, dims in (
        ("Minuting Policy", content.minuting_policy),
        ("Writing Style", content.writing_style),
    ):
        lines += [f"## {section}", ""]
        for d in dims:
            lines += [f"### {d.code} {d.title}", f"Purpose: {d.purpose}", "", d.default_standard]
            if d.application:
                lines += ["", f"Application: {d.application}"]
            for p in d.provisions:
                lines.append(f"- [{p.kind}; {p.provenance}] {p.text}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
