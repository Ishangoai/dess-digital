"""Line up an edited Word copy with the exact copy we exported, paragraph by paragraph.

Order of matching: our hidden paragraph id first, then text similarity within the same agenda
item (for paragraphs whose id was lost), then similarity across items (a moved paragraph).
"""

import re
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from app.minutes.docx_export import ParagraphMark
from app.minutes.docx_read import DocParagraph, ParsedDoc

SAME_ITEM_AT = 0.5  # similarity to pair two paragraphs of the same item when the id is lost
MOVED_AT = 0.8  # similarity to pair paragraphs across items


class ParagraphStatus(StrEnum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    REMOVED = "removed"
    ADDED = "added"
    MOVED = "moved"


class Segment(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str


class Tracked(BaseModel):
    kind: str  # insert, delete or format
    text: str
    author: str


class AlignedParagraph(BaseModel):
    position: int
    item_ref: str  # where it is in the edited copy (for a removed paragraph: where it was)
    original_item_ref: str | None
    original_n: int | None
    paragraph_id: str | None  # the draft paragraph it came from
    role: str  # title, header, heading or body
    status: ParagraphStatus
    similarity: float
    original_text: str
    final_text: str
    diff: list[Segment]
    tracked: list[Tracked]
    comment_ids: list[str]


class Section(BaseModel):
    item_ref: str
    heading: str
    added: bool  # a section the professional added


class Alignment(BaseModel):
    sections: list[Section]
    paragraphs: list[AlignedParagraph]


def align(original: ParsedDoc, marks: list[ParagraphMark], final: ParsedDoc) -> Alignment:
    by_n = {m.n: m for m in marks}
    originals = {n: p for p in original.paragraphs for n in p.marks[:1] if n in by_n}
    headings = {  # without the item number we wrote in front
        m.section: re.sub(r"^\S*\d\S*\s+", "", originals[m.n].text)
        for m in marks
        if m.role == "heading" and m.n in originals
    }
    sections, where = _final_sections(final.paragraphs, by_n, headings)
    finals = [p for p in final.paragraphs if p.text]

    pairs: dict[int, DocParagraph] = {}  # original n -> final paragraph
    taken: set[int] = set()
    for p in finals:  # 1. by hidden id
        for n in p.marks:
            if n in originals and n not in pairs:
                pairs[n] = p
                taken.add(p.index)

    def pair_by_text(threshold: float, same_section: bool) -> None:
        candidates = []
        for n, o in originals.items():
            if n in pairs or not o.text:
                continue
            for p in finals:
                if p.index in taken or (same_section and where[p.index] != by_n[n].section):
                    continue
                if (score := similarity(o.text, p.text)) >= threshold:
                    candidates.append((score, n, p))
        for _, n, p in sorted(candidates, key=lambda c: -c[0]):
            if n not in pairs and p.index not in taken:
                pairs[n] = p
                taken.add(p.index)

    pair_by_text(SAME_ITEM_AT, same_section=True)  # 2. lost id, same item
    pair_by_text(MOVED_AT, same_section=False)  # 3. moved to another item

    rows: list[AlignedParagraph] = []
    matched: dict[int, list[int]] = {}
    for n, p in pairs.items():
        matched.setdefault(p.index, []).append(n)
    for p in finals:
        for n in sorted(matched.get(p.index, [])):
            rows.append(_row(by_n[n], originals[n], p, where[p.index]))
        if p.index not in matched:
            rows.append(_added(p, where[p.index]))
    for n in sorted(originals):  # removed paragraphs go back where they were
        if n not in pairs and originals[n].text:
            _insert_removed(rows, _removed(by_n[n], originals[n]))
    for i, row in enumerate(rows):
        row.position = i
    return Alignment(sections=sections, paragraphs=rows)


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def similarity(before: str, after: str) -> float:
    """Share of words the two texts have in common, in order (1.0 = identical)."""
    a, b = words(before), words(after)
    return SequenceMatcher(None, a, b, autojunk=False).ratio() if a or b else 1.0


def word_diff(before: str, after: str) -> list[Segment]:
    """Word-level differences, keeping spaces and punctuation, as equal/delete/insert runs."""
    a, b = _tokens(before), _tokens(after)
    out: list[Segment] = []

    def push(op: Literal["equal", "insert", "delete"], text: str) -> None:
        if not text:
            return
        if out and out[-1].op == op:
            out[-1].text += text
        else:
            out.append(Segment(op=op, text=text))

    keys_a, keys_b = [t.strip() or " " for t in a], [t.strip() or " " for t in b]
    for op, i1, i2, j1, j2 in SequenceMatcher(None, keys_a, keys_b, autojunk=False).get_opcodes():
        if op == "equal":  # the same words; spacing as in the edited copy
            push("equal", "".join(b[j1:j2]))
        else:
            push("delete", "".join(a[i1:i2]))
            push("insert", "".join(b[j1:j2]))
    return out


TOKEN = re.compile(
    r"[£$€]?\d(?:[\d,.]*\d)?%?\s*"  # a number with its currency sign: £1.2, 5%, 1,250
    r"|\w+\s*|[^\w\s]\s*|\s+"
)


def _tokens(text: str) -> list[str]:
    """Numbers, words and punctuation, each with its trailing space."""
    return TOKEN.findall(text)


def _final_sections(
    paragraphs: list[DocParagraph], by_n: dict[int, ParagraphMark], headings: dict[str, str]
) -> tuple[list[Section], dict[int, str]]:
    """Which agenda item each paragraph of the edited copy sits under."""
    sections = [Section(item_ref="header", heading="Header", added=False)]
    seen, where, current, added = {"header"}, {}, "header", 0
    for p in paragraphs:
        ref = p.item_ref or next(
            (by_n[n].section for n in p.marks if n in by_n and by_n[n].role == "heading"), None
        )
        if ref is None and p.is_heading and p.text:
            ref = next(
                (r for r, h in headings.items() if r not in seen and (_same_heading(h, p.text))),
                None,
            )
            if ref is None:
                added += 1
                ref = f"added-{added}"
                sections.append(Section(item_ref=ref, heading=p.text, added=True))
        if ref is not None:
            current = ref
            if ref not in seen:
                seen.add(ref)
                if not ref.startswith("added-"):
                    sections.append(
                        Section(item_ref=ref, heading=headings.get(ref, p.text), added=False)
                    )
        where[p.index] = current
    for ref, heading in headings.items():  # items the professional deleted outright
        if ref not in seen:
            sections.append(Section(item_ref=ref, heading=heading, added=False))
    return sections, where


def _same_heading(ours: str, theirs: str) -> bool:
    a, b = ours.lower(), theirs.lower()
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() > 0.8


def _tracked(p: DocParagraph) -> list[Tracked]:
    return [Tracked(kind=t.kind, text=t.text, author=t.author) for t in p.tracked]


def _row(mark: ParagraphMark, o: DocParagraph, p: DocParagraph, section: str) -> AlignedParagraph:
    same = " ".join(o.text.split()) == " ".join(p.text.split())
    if section != mark.section:
        status = ParagraphStatus.MOVED
    else:
        status = ParagraphStatus.UNCHANGED if same else ParagraphStatus.CHANGED
    return AlignedParagraph(
        position=0,
        item_ref=section,
        original_item_ref=mark.section,
        original_n=mark.n,
        paragraph_id=mark.paragraph_id,
        role=mark.role,
        status=status,
        similarity=round(similarity(o.text, p.text), 4),
        original_text=o.text,
        final_text=p.text,
        diff=word_diff(o.text, p.text),
        tracked=_tracked(p),
        comment_ids=p.comment_ids,
    )


def _added(p: DocParagraph, section: str) -> AlignedParagraph:
    return AlignedParagraph(
        position=0,
        item_ref=section,
        original_item_ref=None,
        original_n=None,
        paragraph_id=None,
        role="heading" if p.is_heading else "body",
        status=ParagraphStatus.ADDED,
        similarity=0.0,
        original_text="",
        final_text=p.text,
        diff=word_diff("", p.text),
        tracked=_tracked(p),
        comment_ids=p.comment_ids,
    )


def _removed(mark: ParagraphMark, o: DocParagraph) -> AlignedParagraph:
    return AlignedParagraph(
        position=0,
        item_ref=mark.section,
        original_item_ref=mark.section,
        original_n=mark.n,
        paragraph_id=mark.paragraph_id,
        role=mark.role,
        status=ParagraphStatus.REMOVED,
        similarity=0.0,
        original_text=o.text,
        final_text="",
        diff=word_diff(o.text, ""),
        tracked=[],
        comment_ids=[],
    )


def _insert_removed(rows: list[AlignedParagraph], row: AlignedParagraph) -> None:
    """After the nearest earlier paragraph of the same item, else at the top of that item."""
    n = row.original_n or 0
    best = None
    for i, r in enumerate(rows):
        if r.original_item_ref == row.item_ref and r.original_n is not None and r.original_n < n:
            if best is None or (rows[best].original_n or 0) < r.original_n:
                best = i
    if best is not None:
        rows.insert(best + 1, row)
        return
    first = next((i for i, r in enumerate(rows) if r.item_ref == row.item_ref), None)
    rows.insert(first if first is not None else len(rows), row)
