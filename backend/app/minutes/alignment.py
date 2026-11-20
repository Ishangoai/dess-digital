"""Line up an edited Word copy with the exact copy we exported, paragraph by paragraph.

Order of matching: our hidden paragraph id; text similarity within the same agenda item (an id
was lost); position between matched paragraphs (rewritten in place); similarity across items (a
moved paragraph). Table rows are read as one line each.
"""

import re
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from app.minutes.docx_export import ParagraphMark
from app.minutes.docx_read import DocParagraph, ParsedDoc

SAME_ITEM_AT = 0.5  # similarity to pair two paragraphs of the same item when the id is lost
REWRITTEN_AT = 0.2  # ... or when they sit in the same place between matched paragraphs
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
    headings = {m.section: _strip_number(m.text) for m in marks if m.role == "heading"}
    _, original_where = _sections(original.paragraphs, by_n, headings)
    sections, where = _sections(final.paragraphs, by_n, headings)

    # Every paragraph and table row of the original. Ours carry a mark; anything else (text that
    # came with a template) gets a stand-in with a negative number.
    originals: dict[int, DocParagraph] = {}
    info: dict[int, ParagraphMark] = {}
    for p in original.paragraphs:
        if not p.text:
            continue
        n = next((n for n in p.marks if n in by_n), None)
        if n is None:
            n = -(p.index + 1)
            role = "table" if p.in_table else "body"
            info[n] = ParagraphMark(n, original_where[p.index], role, None, p.text)
        else:
            info[n] = by_n[n]
        originals[n] = p
    finals = [p for p in final.paragraphs if p.text]

    pairs: dict[int, DocParagraph] = {}  # original n -> final paragraph
    taken: set[int] = set()

    def pair(n: int, p: DocParagraph) -> None:
        pairs[n] = p
        taken.add(p.index)

    for p in finals:  # 1. by hidden id
        for n in p.marks:
            if n in originals and n not in pairs:
                pair(n, p)

    def pair_by_text(threshold: float, same_section: bool) -> None:
        candidates = []
        for n, o in originals.items():
            if n in pairs:
                continue
            for p in finals:
                if p.index in taken or (same_section and where[p.index] != info[n].section):
                    continue
                if (score := similarity(o.text, p.text)) >= threshold:
                    candidates.append((score, n, p))
        for _, n, p in sorted(candidates, key=lambda c: -c[0]):
            if n not in pairs and p.index not in taken:
                pair(n, p)

    def pair_in_order() -> None:
        """Paragraphs left between two matched ones were rewritten in place. With the same
        number on each side, pair them in order; otherwise each takes its closest match in the
        gap, keeping the order (a rewritten paragraph followed by new ones)."""
        for section in {info[n].section for n in originals}:
            ours = sorted(
                (n for n in originals if info[n].section == section),
                key=lambda n: originals[n].index,
            )
            theirs = [p for p in finals if where[p.index] == section]
            anchors, last = [(-1, -1)], -1
            for n in ours:
                if n in pairs and where[pairs[n].index] == section and pairs[n].index > last:
                    anchors.append((originals[n].index, pairs[n].index))
                    last = pairs[n].index
            anchors.append((10**9, 10**9))
            for (o1, f1), (o2, f2) in zip(anchors, anchors[1:], strict=False):
                gap_o = [n for n in ours if n not in pairs and o1 < originals[n].index < o2]
                gap_f = [p for p in theirs if p.index not in taken and f1 < p.index < f2]
                if len(gap_o) == len(gap_f):
                    for n, p in zip(gap_o, gap_f, strict=True):
                        if similarity(originals[n].text, p.text) >= REWRITTEN_AT:
                            pair(n, p)
                    continue
                after = -1
                for n in gap_o:
                    options = [
                        (similarity(originals[n].text, p.text), p)
                        for p in gap_f
                        if p.index > after and p.index not in taken
                    ]
                    if options and (best := max(options, key=lambda o: o[0]))[0] >= REWRITTEN_AT:
                        pair(n, best[1])
                        after = best[1].index

    pair_by_text(SAME_ITEM_AT, same_section=True)  # 2. lost id, same item
    pair_in_order()  # 3. rewritten in place
    pair_by_text(MOVED_AT, same_section=False)  # 4. moved to another item

    rows: list[AlignedParagraph] = []
    order: dict[int, int] = {}  # id(row) -> position in the original, for removed paragraphs
    matched: dict[int, list[int]] = {}
    for n, p in pairs.items():
        matched.setdefault(p.index, []).append(n)
    for p in finals:
        if p.index not in matched:
            rows.append(_added(p, where[p.index]))
            continue
        for n in sorted(matched[p.index], key=lambda n: originals[n].index):
            row = _row(info[n], originals[n], p, where[p.index])
            order[id(row)] = originals[n].index
            rows.append(row)
    for n in sorted(originals, key=lambda n: originals[n].index):  # removed ones go back in place
        if n not in pairs:
            row = _removed(info[n], originals[n])
            order[id(row)] = originals[n].index
            _insert_removed(rows, row, order)
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


def _sections(
    paragraphs: list[DocParagraph], by_n: dict[int, ParagraphMark], headings: dict[str, str]
) -> tuple[list[Section], dict[int, str]]:
    """Which agenda item each paragraph sits under: by our heading bookmarks, else by heading
    text (in any style, so a heading retyped as bold text in a new document still counts)."""
    sections = [Section(item_ref="header", heading="Header", added=False)]
    seen, where, current, added = {"header"}, {}, "header", 0
    for p in paragraphs:
        ref = p.item_ref or next(
            (by_n[n].section for n in p.marks if n in by_n and by_n[n].role == "heading"), None
        )
        ours = any(n in by_n for n in p.marks)
        if ref is None and p.text and not p.in_table and not ours:
            ref = next(
                (
                    r
                    for r, h in headings.items()
                    if r not in seen and _heading_matches(h, p.text, p.is_heading)
                ),
                None,
            )
            if ref is None and p.is_heading:
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


def _strip_number(text: str) -> str:
    """'4 Financial performance' or '4. Financial performance' -> 'Financial performance'."""
    return re.sub(r"^\S*\d\S*\s+", "", text.strip())


def _heading_matches(ours: str, theirs: str, styled: bool) -> bool:
    a = " ".join(words(_strip_number(ours)))
    b = " ".join(words(_strip_number(theirs)))
    if not a or not b:
        return False
    if styled:  # a Word heading: generous, it can only be a heading
        return a in b or b in a or SequenceMatcher(None, a, b).ratio() > 0.8
    # Plain text must read as the heading itself, not a sentence that mentions it.
    short = len(b.split()) <= len(a.split()) + 3
    return short and (a == b or SequenceMatcher(None, a, b).ratio() >= 0.85)


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
        original_n=mark.n if mark.n > 0 else None,
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
        role="heading" if p.is_heading else "table" if p.in_table else "body",
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
        original_n=mark.n if mark.n > 0 else None,
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


def _insert_removed(
    rows: list[AlignedParagraph], row: AlignedParagraph, order: dict[int, int]
) -> None:
    """After the nearest earlier paragraph of the same item, else at the top of that item."""
    here = order[id(row)]
    best = None
    for i, r in enumerate(rows):
        at = order.get(id(r))
        if r.original_item_ref == row.item_ref and at is not None and at < here:
            if best is None or order[id(rows[best])] < at:
                best = i
    if best is not None:
        rows.insert(best + 1, row)
        return
    first = next((i for i, r in enumerate(rows) if r.item_ref == row.item_ref), None)
    rows.insert(first if first is not None else len(rows), row)
