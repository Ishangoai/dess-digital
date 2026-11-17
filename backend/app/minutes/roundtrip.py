"""Read an edited Word draft back and compare it with what we wrote, item by item."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from pydantic import BaseModel

from app.minutes.docx_export import BOOKMARK_PREFIX, RUN_PREFIX, _format_date, bookmark_name
from app.minutes.extract import _open_docx
from app.minutes.llm_schemas import DraftMinutes, MeetingHeader
from app.minutes.profile_content import PresentationSettings

HEADER = "header"
EDITED_AT = 0.6  # below this similarity an item counts as rewritten
REMOVED = {qn("w:del"), qn("w:moveFrom")}


class ChangeStatus(StrEnum):
    UNCHANGED = "unchanged"
    EDITED = "edited"
    REWRITTEN = "rewritten"
    DELETED = "deleted"
    ADDED = "added"


class ItemChange(BaseModel):
    item_ref: str
    heading: str
    status: ChangeStatus
    similarity: float
    words_added: int
    words_removed: int
    draft_text: str
    final_text: str


class ReviewerComment(BaseModel):
    author: str
    text: str


class Comparison(BaseModel):
    run_id: str | None  # the run id found in the file, if any
    items: list[ItemChange]
    comments: list[ReviewerComment]
    similarity: float  # word-weighted over all items, 0 to 1

    def counts(self) -> dict[str, int]:
        return {s.value: sum(i.status == s for i in self.items) for s in ChangeStatus}


class WrongDraftError(ValueError):
    pass


@dataclass
class _Section:
    ref: str | None  # None: a section the user added
    heading: str
    paragraphs: list[str] = field(default_factory=list)


def compare_final(
    data: bytes, draft: DraftMinutes, run_id: str, presentation: PresentationSettings
) -> Comparison:
    """Compare an uploaded .docx with the draft of run `run_id`, as it was exported."""
    doc = _open_docx(data)
    found = (doc.core_properties.identifier or "").removeprefix(RUN_PREFIX) or None
    if found and found != run_id:
        raise WrongDraftError("this Word file was downloaded from a different draft")

    sections = _sections(doc.paragraphs, draft)
    header = _header_text(draft.header, presentation)
    changes = [_change(HEADER, "Header", header, sections.pop(HEADER, None))]
    for item in draft.items:
        final = sections.pop(item.item_ref, None)
        draft_text = "\n".join(p.text for p in item.paragraphs)
        changes.append(_change(item.item_ref, item.heading, draft_text, final))
    for n, s in enumerate(sections.values(), 1):  # what is left was added by the user
        changes.append(_change(f"added-{n}", s.heading, "", s))

    comments = [
        ReviewerComment(author=c.author or "", text=c.text)
        for c in doc.comments
        if c.text.strip() and c.author != presentation.comment_author
    ]
    return Comparison(run_id=found, items=changes, comments=comments, similarity=_weighted(changes))


def accepted_text(paragraph: Paragraph) -> str:
    """Paragraph text with tracked changes accepted: insertions kept, deletions dropped."""
    parts = []
    for el in paragraph._p.iter(qn("w:t"), qn("w:tab")):
        if any(a.tag in REMOVED for a in el.iterancestors()):
            continue
        parts.append("\t" if el.tag == qn("w:tab") else el.text or "")
    return "".join(parts).strip()


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def similarity(draft_text: str, final_text: str) -> float:
    """Share of words the two texts have in common, in order (1.0 = identical)."""
    a, b = words(draft_text), words(final_text)
    return SequenceMatcher(None, a, b, autojunk=False).ratio() if a or b else 1.0


def _sections(paragraphs: list[Paragraph], draft: DraftMinutes) -> dict[str, _Section]:
    """Split the document at item headings: by our bookmarks, else by matching heading text."""
    by_bookmark = {bookmark_name(i.item_ref): i.item_ref for i in draft.items}
    headings = {i.item_ref: i.heading for i in draft.items}
    sections: dict[str, _Section] = {HEADER: _Section(HEADER, "Header")}
    current = sections[HEADER]
    added = 0
    for p in paragraphs:
        text = accepted_text(p)
        ref = _bookmarked(p, by_bookmark) or _heading_match(p, text, headings, sections)
        if ref:
            current = sections.setdefault(ref, _Section(ref, headings[ref]))
            current.heading = text
            continue
        if _is_heading(p) and text and text != "Actions":
            added += 1
            current = sections.setdefault(f"+{added}", _Section(None, text))
            continue
        if text and text != "Actions":
            current.paragraphs.append(_strip_number(text, current.heading))
    return sections


def _bookmarked(p: Paragraph, by_bookmark: dict[str, str]) -> str | None:
    for b in p._p.iter(qn("w:bookmarkStart")):
        name = b.get(qn("w:name")) or ""
        if name.startswith(BOOKMARK_PREFIX) and name in by_bookmark:
            return by_bookmark[name]
    return None


def _heading_match(
    p: Paragraph, text: str, headings: dict[str, str], seen: dict[str, _Section]
) -> str | None:
    """A heading whose bookmark was lost: match it to an item by its text."""
    if not _is_heading(p):
        return None
    for ref, heading in headings.items():
        if ref not in seen and (heading.lower() in text.lower() or _ratio(heading, text) > 0.8):
            return ref
    return None


def _is_heading(p: Paragraph) -> bool:
    style = p.style.name if p.style is not None else ""
    return bool(style) and style.lower().startswith("heading")


def _strip_number(text: str, heading: str) -> str:
    """Drop our '4.2 ' paragraph numbers, which are plain text in the export."""
    number = heading.split(" ", 1)[0] if heading[:1].isalnum() else ""
    if number and re.match(rf"{re.escape(number)}\.\d+\s", text):
        return text.split(" ", 1)[1] if " " in text else ""
    return text


def _header_text(h: MeetingHeader, p: PresentationSettings) -> str:
    """The header as the export writes it, so an untouched header compares as unchanged."""
    date = _format_date(h.meeting_date, p.date_style) if h.meeting_date else ""
    lines = [h.title, p.status_label or "", date, h.time_and_place or ""]
    attendance = (("Present", h.present), ("In attendance", h.in_attendance),
                  ("Apologies", h.apologies))  # fmt: skip
    for label, names in attendance:
        if names:
            lines += [label, *names]
    return "\n".join(x for x in lines if x)


def _change(ref: str, heading: str, draft_text: str, final: _Section | None) -> ItemChange:
    final_text = "\n".join(final.paragraphs) if final else ""
    a, b = words(draft_text), words(final_text)
    added = removed = 0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            removed += i2 - i1
            added += j2 - j1
    ratio = matcher.ratio() if a or b else 1.0
    if not draft_text:
        status = ChangeStatus.ADDED
    elif final is None or not b:
        status, ratio = ChangeStatus.DELETED, 0.0
    elif a == b:
        status = ChangeStatus.UNCHANGED
    else:
        status = ChangeStatus.EDITED if ratio >= EDITED_AT else ChangeStatus.REWRITTEN
    return ItemChange(
        item_ref=ref,
        heading=final.heading if final and final.ref is None else heading,
        status=status,
        similarity=round(ratio, 4),
        words_added=added,
        words_removed=removed,
        draft_text=draft_text,
        final_text=final_text,
    )


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _weighted(changes: list[ItemChange]) -> float:
    """Similarity weighted by item size, so a rewritten long item counts for more."""
    weights = [max(len(words(c.draft_text)), len(words(c.final_text)), 1) for c in changes]
    total = sum(weights)
    return round(sum(c.similarity * w for c, w in zip(changes, weights, strict=True)) / total, 4)
