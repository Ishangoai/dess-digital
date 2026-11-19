"""Read an edited copy of the exported minutes and line it up with the original export.

The final text of each paragraph is read from the XML: python-docx's paragraph.text skips
tracked insertions. Tracked insertions are accepted and tracked deletions removed.
"""

import difflib
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.oxml.parser import parse_xml
from pydantic import BaseModel

from app.minutes.docx_export import IDENTIFIER_PREFIX, ExportManifest
from app.minutes.extract import UnsupportedFileError

HEADER_SECTION = "header"
SAME_SECTION_THRESHOLD = 0.6
CROSS_SECTION_THRESHOLD = 0.75
HEADING_TEXT_THRESHOLD = 0.85

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
COMMENTS_EXTENDED_RT = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"

W_P, W_T, W_TBL, W_TR = qn("w:p"), qn("w:t"), qn("w:tbl"), qn("w:tr")
W_INS, W_DEL, W_MOVE_FROM, W_MOVE_TO = qn("w:ins"), qn("w:del"), qn("w:moveFrom"), qn("w:moveTo")
W_RPR, W_PPR = qn("w:rPr"), qn("w:pPr")
W_RPR_CHANGE, W_PPR_CHANGE = qn("w:rPrChange"), qn("w:pPrChange")

# Never part of the final text: deleted or moved-away text, properties, field codes and
# objects with their own text (text boxes).
_SKIP = {
    qn(t)
    for t in (
        "w:del",
        "w:moveFrom",
        "w:pPr",
        "w:rPr",
        "w:delText",
        "w:instrText",
        "w:delInstrText",
        "w:drawing",
        "w:pict",
        "w:object",
        "w:footnoteReference",
        "w:endnoteReference",
        "w:commentReference",
    )
} | {f"{{{MC}}}AlternateContent"}
_CHARS = {qn("w:tab"): "\t", qn("w:ptab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\n"}
_CHARS[qn("w:noBreakHyphen")] = "-"


# reading one file


ChangeKind = Literal["insertion", "deletion", "move_from", "move_to", "formatting"]


class TrackedChange(BaseModel):
    kind: ChangeKind
    text: str
    author: str | None
    date: str | None


class Block(BaseModel):
    """One paragraph (or table row) with its final text."""

    index: int
    text: str
    section: str = HEADER_SECTION  # item ref, "actions" or "header"
    heading_key: str | None = None  # set on item headings
    paragraph_ids: list[str] = []  # minute paragraphs bookmarked here
    bookmarked: bool = False  # heading found by bookmark rather than by text
    in_table: bool = False
    tracked_changes: list[TrackedChange] = []
    comment_ids: list[str] = []


class RawComment(BaseModel):
    comment_id: str
    author: str | None
    date: str | None
    text: str
    parent_id: str | None
    resolved: bool
    block_index: int | None


@dataclass
class ReadDocument:
    blocks: list[Block]
    comments: list[RawComment]
    identifier: str | None

    def export_id(self) -> str | None:
        if self.identifier and self.identifier.startswith(IDENTIFIER_PREFIX):
            return self.identifier.removeprefix(IDENTIFIER_PREFIX)
        return None


@dataclass
class _Unit:
    elements: list[Any]
    in_table: bool
    text: str
    mark_deleted: bool = False
    bookmarks: list[str] = field(default_factory=list)


def read_docx(
    data: bytes,
    manifest: ExportManifest,
    heading_hints: list[tuple[str, str]] | None = None,
) -> ReadDocument:
    """Read a Word file into blocks. heading_hints (key, text) find headings without bookmarks."""
    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises several unrelated types for bad files
        raise UnsupportedFileError(f"not a readable .docx file: {e}") from e

    body = doc.element.body
    units = _merge_deleted_marks(list(_units(body)))
    owner: dict[Any, int] = {}
    for i, unit in enumerate(units):
        for el in unit.elements:
            owner[el] = i

    def unit_of(marker: Any) -> int | None:
        found = _paragraph_of(marker)
        return owner.get(found) if found is not None else None

    for start in body.iter(qn("w:bookmarkStart")):
        i = unit_of(start)
        if i is not None:
            units[i].bookmarks.append(start.get(qn("w:name")) or "")

    comment_unit: dict[str, int] = {}
    for start in body.iter(qn("w:commentRangeStart")):
        i = unit_of(start)
        if i is not None:
            comment_unit.setdefault(start.get(qn("w:id")) or "", i)
    for ref in body.iter(qn("w:commentReference")):
        i = unit_of(ref)
        if i is not None:
            comment_unit.setdefault(ref.get(qn("w:id")) or "", i)

    # Blank paragraphs carry nothing to compare; keep indexes dense.
    index_of: dict[int, int] = {}
    blocks: list[Block] = []
    for i, unit in enumerate(units):
        if not unit.text.strip():
            continue
        index_of[i] = len(blocks)
        blocks.append(
            Block(
                index=len(blocks),
                text=unit.text,
                paragraph_ids=[
                    manifest.paragraphs[b] for b in unit.bookmarks if b in manifest.paragraphs
                ],
                heading_key=next(
                    (manifest.headings[b] for b in unit.bookmarks if b in manifest.headings), None
                ),
                in_table=unit.in_table,
                tracked_changes=[c for el in unit.elements for c in _tracked_changes(el)],
            )
        )
    for b in blocks:
        b.bookmarked = b.heading_key is not None
    if heading_hints:
        _headings_by_text(blocks, heading_hints)
    _assign_sections(blocks)

    comments = _read_comments(doc)
    for c in comments:
        unit_index = comment_unit.get(c.comment_id)
        c.block_index = index_of.get(unit_index) if unit_index is not None else None
        if c.block_index is not None:
            blocks[c.block_index].comment_ids.append(c.comment_id)
    return ReadDocument(blocks, comments, doc.core_properties.identifier or None)


def _paragraph_of(marker: Any) -> Any:
    """The paragraph a bookmark or comment marker is in, else the next one after it."""
    el = marker
    while el is not None:
        if el.tag == W_P:
            return el
        el = el.getparent()
    el = marker
    while el is not None:
        for sibling in el.itersiblings():
            found = sibling if sibling.tag == W_P else next(sibling.iter(W_P), None)
            if found is not None:
                return found
        el = el.getparent()
    return None


def _units(container: Any) -> Iterator[_Unit]:
    for child in container:
        if child.tag == W_P:
            p_pr = child.find(W_PPR)
            r_pr = p_pr.find(W_RPR) if p_pr is not None else None
            mark_deleted = r_pr is not None and r_pr.find(W_DEL) is not None
            yield _Unit([child], False, final_text(child), mark_deleted)
        elif child.tag == W_TBL:
            for row in child.iter(W_TR):
                cells = [
                    " ".join(final_text(p) for p in tc.iter(W_P)).strip()
                    for tc in row.iterchildren(qn("w:tc"))
                ]
                yield _Unit(list(row.iter(W_P)), True, " | ".join(cells))
        elif child.tag in (qn("w:sdt"), qn("w:sdtContent"), qn("w:customXml")):
            yield from _units(child)


def _merge_deleted_marks(units: list[_Unit]) -> list[_Unit]:
    """A deleted paragraph mark joins the paragraph to the next, as Word does on accept."""
    merged: list[_Unit] = []
    for unit in units:
        prev = merged[-1] if merged else None
        if prev and prev.mark_deleted and not prev.in_table and not unit.in_table:
            prev.elements += unit.elements
            prev.text += unit.text
            prev.mark_deleted = unit.mark_deleted
        else:
            merged.append(unit)
    return merged


def final_text(el: Any) -> str:
    parts: list[str] = []
    for child in el:
        tag = child.tag
        if not isinstance(tag, str) or tag in _SKIP:  # XML comments have no str tag
            continue
        if tag == W_T:
            parts.append(child.text or "")
        elif tag in _CHARS:
            parts.append(_CHARS[tag])
        else:
            parts.append(final_text(child))
    return "".join(parts)


def _removed_text(el: Any) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:delText"), W_T))


def _tracked_changes(p: Any) -> Iterator[TrackedChange]:
    for el in p.iter(W_INS, W_DEL, W_MOVE_FROM, W_MOVE_TO, W_RPR_CHANGE, W_PPR_CHANGE):
        if el.getparent().tag == W_RPR and el.tag in (W_INS, W_DEL):
            continue  # paragraph mark inserted or deleted
        if el.tag in (W_INS, W_MOVE_TO):
            kind: ChangeKind = "insertion" if el.tag == W_INS else "move_to"
            text = final_text(el)
        elif el.tag in (W_DEL, W_MOVE_FROM):
            kind = "deletion" if el.tag == W_DEL else "move_from"
            text = _removed_text(el)
        else:
            kind = "formatting"
            run = el.getparent().getparent()
            text = final_text(run) if el.tag == W_RPR_CHANGE else ""
        if text or kind == "formatting":
            yield TrackedChange(
                kind=kind, text=text, author=el.get(qn("w:author")), date=el.get(qn("w:date"))
            )


def _headings_by_text(blocks: list[Block], hints: list[tuple[str, str]]) -> None:
    """Find item headings whose bookmark was lost, by their text."""
    found = {b.heading_key for b in blocks if b.heading_key}
    for key, text in hints:
        if key in found:
            continue
        target = normalise(text)
        candidates = [
            b
            for b in blocks
            if b.heading_key is None
            and not b.paragraph_ids
            and not b.in_table
            and len(b.text.split()) <= max(15, len(target.split()) + 5)
        ]
        best = max(candidates, key=lambda b: similarity(b.text, text), default=None)
        if best is not None and similarity(best.text, text) >= HEADING_TEXT_THRESHOLD:
            best.heading_key = key
            found.add(key)


def _assign_sections(blocks: list[Block]) -> None:
    section = HEADER_SECTION
    for b in blocks:
        if b.heading_key:
            section = b.heading_key
        b.section = section


def _read_comments(doc: Any) -> list[RawComment]:
    part = next((r.target_part for r in doc.part.rels.values() if r.reltype == RT.COMMENTS), None)
    if part is None:
        return []
    root = part.element if hasattr(part, "element") else parse_xml(part.blob)

    para_owner: dict[str, str] = {}
    comments: list[RawComment] = []
    for el in root.iter(qn("w:comment")):
        cid = el.get(qn("w:id")) or ""
        paragraphs = list(el.iter(W_P))
        if paragraphs:
            para_id = paragraphs[-1].get(f"{{{W14}}}paraId")
            if para_id:
                para_owner[para_id] = cid
        comments.append(
            RawComment(
                comment_id=cid,
                author=el.get(qn("w:author")),
                date=el.get(qn("w:date")),
                text="\n".join(final_text(p) for p in paragraphs).strip(),
                parent_id=None,
                resolved=False,
                block_index=None,
            )
        )

    extended = next(
        (r.target_part for r in doc.part.rels.values() if r.reltype == COMMENTS_EXTENDED_RT), None
    )
    if extended is not None:
        by_id = {c.comment_id: c for c in comments}
        for ex in parse_xml(extended.blob).iter(f"{{{W15}}}commentEx"):
            cid = para_owner.get(ex.get(f"{{{W15}}}paraId") or "")
            parent = para_owner.get(ex.get(f"{{{W15}}}paraIdParent") or "")
            if cid in by_id:
                by_id[cid].parent_id = parent if parent != cid else None
                by_id[cid].resolved = ex.get(f"{{{W15}}}done") == "1"
    return comments


# comparing two files


Status = Literal["unchanged", "changed", "removed", "added", "moved"]
STATUSES: tuple[Status, ...] = ("unchanged", "changed", "removed", "added", "moved")


class DiffSegment(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str


class ParagraphChange(BaseModel):
    status: Status
    section: str
    from_section: str | None = None  # where a moved paragraph was
    paragraph_id: str | None
    heading: bool
    original: str | None
    edited: str | None
    original_index: int | None
    edited_index: int | None
    matched_by: Literal["bookmark", "text"] | None
    similarity: float | None
    text_changed: bool
    format_only: bool  # same words; only whitespace or tracked formatting differs
    diff: list[DiffSegment]
    tracked_changes: list[TrackedChange]
    comment_ids: list[str]


class SectionChanges(BaseModel):
    section: str
    heading: str
    counts: dict[str, int]
    changes: list[ParagraphChange]


class CommentReply(BaseModel):
    comment_id: str
    author: str | None
    date: str | None
    text: str


class CommentThread(BaseModel):
    comment_id: str
    author: str | None
    date: str | None
    text: str
    question_id: str | None  # set when this is one of the draft's clarification questions
    resolved: bool
    section: str | None
    paragraph_id: str | None
    edited_index: int | None
    replies: list[CommentReply]


class Comparison(BaseModel):
    counts: dict[str, int]
    sections: list[SectionChanges]
    comments: list[CommentThread]
    tracked_change_authors: list[str]
    bookmarks_expected: int
    bookmarks_found: int


def compare(original: ReadDocument, edited: ReadDocument, manifest: ExportManifest) -> Comparison:
    orig, ed = original.blocks, edited.blocks
    pairs: dict[int, tuple[int, Literal["bookmark", "text"]]] = {}

    # 1. by bookmark; if several originals land in one edited block (merged), the closest wins
    by_paragraph = {pid: b.index for b in ed for pid in b.paragraph_ids}
    by_heading = {b.heading_key: b.index for b in ed if b.heading_key}
    claims: dict[int, list[int]] = {}
    for o in orig:
        target = (
            by_heading.get(o.heading_key)
            if o.heading_key
            else next((by_paragraph[p] for p in o.paragraph_ids if p in by_paragraph), None)
        )
        if target is not None:
            claims.setdefault(target, []).append(o.index)
    for e_index, o_indexes in claims.items():
        best = max(o_indexes, key=lambda i: similarity(orig[i].text, ed[e_index].text))
        heading_by_text = orig[best].heading_key and not ed[e_index].bookmarked
        pairs[best] = (e_index, "text" if heading_by_text else "bookmark")

    # 2. by text within the same agenda item, then 3. across items (a move)
    taken = {e for e, _ in pairs.values()}
    for threshold, same_section in (
        (SAME_SECTION_THRESHOLD, True),
        (CROSS_SECTION_THRESHOLD, False),
    ):
        candidates: list[tuple[float, int, int]] = []
        for o in orig:
            if o.index in pairs:
                continue
            for e in ed:
                if e.index in taken or (same_section and e.section != o.section):
                    continue
                score = similarity(o.text, e.text, threshold)
                if score >= threshold:
                    candidates.append((score, o.index, e.index))
        for _, o_index, e_index in sorted(candidates, reverse=True):
            if o_index not in pairs and e_index not in taken:
                pairs[o_index] = (e_index, "text")
                taken.add(e_index)

    in_order = _longest_increasing(sorted(pairs.items(), key=lambda kv: kv[1][0]))
    changes: list[tuple[tuple[int, int, int], ParagraphChange]] = []
    for o_index, (e_index, by) in pairs.items():
        o, e = orig[o_index], ed[e_index]
        moved = o.section != e.section or o_index not in in_order
        text_changed = normalise(o.text) != normalise(e.text)
        status: Status = "moved" if moved else "changed" if text_changed else "unchanged"
        change = _change(status, o, e, by)
        change.from_section = o.section if moved and o.section != e.section else None
        changes.append(((e_index, 0, o_index), change))

    for o in orig:
        if o.index not in pairs:
            before = next((pairs[i][0] for i in range(o.index - 1, -1, -1) if i in pairs), -1)
            changes.append(((before, 1, o.index), _change("removed", o, None, None)))
    for e in ed:
        if e.index not in taken:
            changes.append(((e.index, 0, -1), _change("added", None, e, None)))

    headings = {o.heading_key: o.text for o in orig if o.heading_key}
    order = list(
        dict.fromkeys([HEADER_SECTION, *[o.section for o in orig], *[e.section for e in ed]])
    )
    sections: list[SectionChanges] = []
    for key in order:
        mine = [c for k, c in sorted(changes, key=lambda kc: kc[0]) if c.section == key]
        if mine:
            sections.append(
                SectionChanges(
                    section=key,
                    heading=headings.get(key, "Meeting details" if key == HEADER_SECTION else key),
                    counts=_counts(mine),
                    changes=mine,
                )
            )

    expected = {pid for o in orig for pid in o.paragraph_ids}
    found = {pid for e in ed for pid in e.paragraph_ids}
    authors = sorted({c.author for b in ed for c in b.tracked_changes if c.author})
    return Comparison(
        counts=_counts([c for _, c in changes]),
        sections=sections,
        comments=_threads(original, edited, manifest),
        tracked_change_authors=authors,
        bookmarks_expected=len(expected),
        bookmarks_found=len(expected & found),
    )


def _change(status: Status, o: Block | None, e: Block | None, by: Any) -> ParagraphChange:
    a, b = (o.text if o else ""), (e.text if e else "")
    text_changed = normalise(a) != normalise(b)
    formatting = any(c.kind == "formatting" for c in (e.tracked_changes if e else []))
    pid = (o.paragraph_ids[0] if o and o.paragraph_ids else None) or (
        e.paragraph_ids[0] if e and e.paragraph_ids else None
    )
    return ParagraphChange(
        status=status,
        section=e.section if e else o.section if o else HEADER_SECTION,
        paragraph_id=pid,
        heading=bool((o and o.heading_key) or (e and e.heading_key)),
        original=o.text if o else None,
        edited=e.text if e else None,
        original_index=o.index if o else None,
        edited_index=e.index if e else None,
        matched_by=by,
        similarity=round(similarity(a, b), 3) if o and e else None,
        text_changed=text_changed,
        format_only=bool(o and e and not text_changed and (a != b or formatting)),
        diff=word_diff(a, b),
        tracked_changes=e.tracked_changes if e else [],
        comment_ids=e.comment_ids if e else [],
    )


def _threads(
    original: ReadDocument, edited: ReadDocument, manifest: ExportManifest
) -> list[CommentThread]:
    """Edited comments as threads, with replies to the draft's questions linked to them."""
    asked = {c.comment_id: c for c in original.comments if c.comment_id in manifest.questions}
    by_text = {normalise(c.text): manifest.questions[cid] for cid, c in asked.items()}

    def question_id(c: RawComment) -> str | None:
        if normalise(c.text) in by_text:
            return by_text[normalise(c.text)]
        # Word may renumber comments; trust the id only if the author also matches.
        source = asked.get(c.comment_id)
        return manifest.questions[c.comment_id] if source and source.author == c.author else None

    by_id = {c.comment_id: c for c in edited.comments}

    def root(c: RawComment) -> RawComment:
        seen = {c.comment_id}
        while c.parent_id and c.parent_id in by_id and c.parent_id not in seen:
            c = by_id[c.parent_id]
            seen.add(c.comment_id)
        return c

    threads: dict[str, CommentThread] = {}
    for c in edited.comments:
        if root(c) is not c:
            continue
        block = edited.blocks[c.block_index] if c.block_index is not None else None
        threads[c.comment_id] = CommentThread(
            comment_id=c.comment_id,
            author=c.author,
            date=c.date,
            text=c.text,
            question_id=question_id(c),
            resolved=c.resolved,
            section=block.section if block else None,
            paragraph_id=block.paragraph_ids[0] if block and block.paragraph_ids else None,
            edited_index=c.block_index,
            replies=[],
        )
    for c in edited.comments:
        top = root(c)
        if top is not c:
            threads[top.comment_id].replies.append(
                CommentReply(comment_id=c.comment_id, author=c.author, date=c.date, text=c.text)
            )
    return list(threads.values())


def _counts(changes: list[ParagraphChange]) -> dict[str, int]:
    return {s: sum(1 for c in changes if c.status == s) for s in STATUSES}


def _longest_increasing(
    pairs: list[tuple[int, tuple[int, Any]]],
) -> set[int]:
    """Original indexes of the largest set of pairs that kept their relative order."""
    seq = [o for o, _ in pairs]
    tails: list[int] = []  # index into seq of the smallest tail for each length
    prev = [-1] * len(seq)
    for i, value in enumerate(seq):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[tails[mid]] < value:
                lo = mid + 1
            else:
                hi = mid
        prev[i] = tails[lo - 1] if lo else -1
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    keep: set[int] = set()
    i = tails[-1] if tails else -1
    while i >= 0:
        keep.add(seq[i])
        i = prev[i]
    return keep


# text helpers


def normalise(text: str) -> str:
    return " ".join(text.split())


def similarity(a: str, b: str, threshold: float = 0.0) -> float:
    """Word-level similarity, 0 to 1. Below threshold, a cheap upper bound may be returned."""
    matcher = difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False)
    if threshold and (matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold):
        return 0.0
    return matcher.ratio()


def word_diff(a: str, b: str) -> list[DiffSegment]:
    """Word-level differences; the UI puts a space between segments."""
    aw, bw = a.split(), b.split()
    segments: list[DiffSegment] = []

    def add(op: Literal["equal", "insert", "delete"], words: list[str]) -> None:
        if not words:
            return
        if segments and segments[-1].op == op:
            segments[-1].text += " " + " ".join(words)
        else:
            segments.append(DiffSegment(op=op, text=" ".join(words)))

    matcher = difflib.SequenceMatcher(None, aw, bw, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("equal", aw[i1:i2])
        else:
            add("delete", aw[i1:i2])
            add("insert", bw[j1:j2])
    return segments
