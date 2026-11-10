"""Meeting evidence with stable line numbers the model can cite."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from app.minutes.llm_schemas import LineRef


class SourceRole(StrEnum):
    AGENDA = "agenda"
    TRANSCRIPT = "transcript"
    NOTES = "notes"
    PAPER = "paper"


SOURCE_TAGS = {
    SourceRole.AGENDA: "agenda",
    SourceRole.TRANSCRIPT: "transcript",
    SourceRole.NOTES: "notes",
    SourceRole.PAPER: "paper",
}


class MeetingInfo(BaseModel):
    """Details the user supplies alongside the files."""

    organisation: str | None = None
    body_name: str | None = None
    meeting_date: str | None = None
    meeting_type: str | None = None
    notes: str | None = None

    def is_empty(self) -> bool:
        return not any(self.model_dump().values())


@dataclass(frozen=True)
class SourceText:
    source_id: str  # A, T, N, P1, P2 ...
    role: SourceRole
    filename: str
    text: str

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def numbered(self) -> str:
        """Non-blank lines prefixed with source id and line number, e.g. 'T12| ...'."""
        return "\n".join(
            f"{self.source_id}{n}| {line}" for n, line in enumerate(self.lines, 1) if line.strip()
        )


def source_ids_for(roles: Iterable[SourceRole]) -> list[str]:
    """Assign ids in upload order: A, T, N, then P1, P2 ... for papers."""
    ids, papers = [], 0
    for role in roles:
        if role == SourceRole.PAPER:
            papers += 1
            ids.append(f"P{papers}")
        else:
            ids.append(role.value[0].upper())
    return ids


@dataclass(frozen=True)
class EvidenceBundle:
    sources: list[SourceText]

    def get(self, source_id: str) -> SourceText | None:
        return next((s for s in self.sources if s.source_id == source_id), None)

    def total_chars(self) -> int:
        return sum(len(s.text) for s in self.sources)

    def render(self) -> str:
        blocks = []
        for s in self.sources:
            tag = SOURCE_TAGS[s.role]
            blocks.append(
                f'<{tag} source_id="{s.source_id}" filename="{s.filename}">\n'
                f"{s.numbered()}\n</{tag}>"
            )
        return "\n\n".join(blocks)

    def check_ref(self, ref: LineRef) -> str | None:
        """Error message if the reference does not point at real lines."""
        source = self.get(ref.source_id)
        if source is None:
            return f"unknown source '{ref.source_id}'"
        if not 1 <= ref.start <= ref.end <= len(source.lines):
            return f"{ref.source_id}{ref.start}-{ref.end} is outside 1-{len(source.lines)}"
        return None

    def excerpt(self, ref: LineRef, max_chars: int = 600) -> str:
        source = self.get(ref.source_id)
        if source is None:
            return ""
        text = "\n".join(source.lines[max(ref.start, 1) - 1 : ref.end]).strip()
        return text if len(text) <= max_chars else text[: max_chars - 3] + "..."

    def uncovered(
        self, refs: Iterable[LineRef], roles: Iterable[SourceRole] = (SourceRole.TRANSCRIPT,)
    ) -> list[LineRef]:
        """Non-blank lines of the given roles that no reference covers, as ranges."""
        refs = list(refs)
        gaps: list[LineRef] = []
        for source in (s for s in self.sources if s.role in set(roles)):
            covered = {
                n
                for r in refs
                if r.source_id == source.source_id
                for n in range(r.start, r.end + 1)
            }
            start = prev = None
            for n, line in enumerate(source.lines, 1):
                if not line.strip() or n in covered:
                    continue
                if prev is not None and _only_blank_between(source.lines, prev, n):
                    prev = n
                    continue
                if start is not None and prev is not None:
                    gaps.append(LineRef(source_id=source.source_id, start=start, end=prev))
                start = prev = n
            if start is not None and prev is not None:
                gaps.append(LineRef(source_id=source.source_id, start=start, end=prev))
        return gaps


def _only_blank_between(lines: list[str], a: int, b: int) -> bool:
    return all(not lines[i - 1].strip() for i in range(a + 1, b))
