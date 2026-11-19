"""Read a Word document back: paragraphs with our hidden ids, tracked changes and comments.

python-docx's `paragraph.text` skips text inside tracked insertions, so the XML is walked here:
final text keeps insertions and drops deletions; the tracked changes and comments are kept as
evidence of what the professional did and said.
"""

from dataclasses import dataclass, field
from typing import Any

from docx.document import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.minutes.docx_export import BOOKMARK_PREFIX, PARAGRAPH_BOOKMARK, read_identifier
from app.minutes.extract import _open_docx

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
REMOVED = {qn("w:del"), qn("w:moveFrom")}
ADDED = {qn("w:ins"), qn("w:moveTo")}
FORMAT_CHANGES = {qn("w:rPrChange"), qn("w:pPrChange")}


@dataclass(frozen=True)
class TrackedChange:
    kind: str  # insert, delete or format
    text: str
    author: str


@dataclass
class DocParagraph:
    index: int
    text: str  # tracked changes accepted
    before_tracking: str  # as it read before the tracked changes in it
    marks: list[int]  # our hidden paragraph ids found in it
    item_ref: str | None  # set on item headings that kept our bookmark
    is_heading: bool
    tracked: list[TrackedChange] = field(default_factory=list)
    comment_ids: list[str] = field(default_factory=list)
    in_table: bool = False  # a table row, read as one line: "cell | cell | cell"


@dataclass(frozen=True)
class DocComment:
    id: str
    author: str
    text: str
    paragraph_index: int | None  # where it is anchored
    anchor: str  # the text it covers
    parent_id: str | None  # set on replies


@dataclass(frozen=True)
class ParsedDoc:
    run_id: str | None
    export_id: str | None
    paragraphs: list[DocParagraph]
    comments: list[DocComment]


def read_docx(data: bytes, item_refs: dict[str, str] | None = None) -> ParsedDoc:
    """`item_refs` maps our item bookmark names to item refs (bookmark_name(ref) -> ref)."""
    doc = _open_docx(data)
    run_id, export_id = read_identifier(doc.core_properties.identifier)
    paragraphs: list[DocParagraph] = []
    anchors: dict[str, tuple[int, str]] = {}
    for child in doc.element.body.iterchildren():  # paragraphs and tables, in document order
        if child.tag == qn("w:p"):
            para, found = _paragraph(len(paragraphs), Paragraph(child, doc), item_refs or {})
        elif child.tag == qn("w:tbl"):
            for row in Table(child, doc).rows:
                para, found = _row(len(paragraphs), row.cells, item_refs or {})
                paragraphs.append(para)
                anchors.update(found)
            continue
        else:
            continue
        paragraphs.append(para)
        anchors.update(found)
    for para in paragraphs:
        para.comment_ids = [cid for cid, (i, _) in anchors.items() if i == para.index]
    return ParsedDoc(run_id, export_id, paragraphs, _comments(doc, anchors))


def _paragraph(
    index: int, p: Paragraph, item_refs: dict[str, str]
) -> tuple[DocParagraph, dict[str, tuple[int, str]]]:
    final, before, tracked = [], [], []
    open_comments: dict[str, list[str]] = {}
    anchors: dict[str, tuple[int, str]] = {}
    marks, item_ref = [], None
    for el in p._p.iter():
        tag = el.tag
        if tag == qn("w:bookmarkStart"):
            name = el.get(qn("w:name")) or ""
            if name.startswith(PARAGRAPH_BOOKMARK) and name[len(PARAGRAPH_BOOKMARK) :].isdigit():
                marks.append(int(name[len(PARAGRAPH_BOOKMARK) :]))
            elif name.startswith(BOOKMARK_PREFIX) and name in item_refs:
                item_ref = item_refs[name]
        elif tag == qn("w:commentRangeStart"):
            open_comments[el.get(qn("w:id")) or ""] = []
        elif tag == qn("w:commentRangeEnd"):
            cid = el.get(qn("w:id")) or ""
            anchors[cid] = (index, "".join(open_comments.pop(cid, [])))
        elif tag == qn("w:commentReference"):
            cid = el.get(qn("w:id")) or ""
            anchors.setdefault(cid, (index, ""))
        elif tag in (qn("w:t"), qn("w:delText"), qn("w:tab")):
            text = "\t" if tag == qn("w:tab") else el.text or ""
            ancestors = {a.tag for a in el.iterancestors()}
            removed, added = bool(ancestors & REMOVED), bool(ancestors & ADDED)
            if not removed:
                final.append(text)
                for parts in open_comments.values():
                    parts.append(text)
            if not added:
                before.append(text)
        elif tag in REMOVED | ADDED:
            text = "".join(t.text or "" for t in el.iter(qn("w:t"), qn("w:delText")))
            if text:
                kind = "delete" if tag in REMOVED else "insert"
                tracked.append(TrackedChange(kind, text, el.get(qn("w:author")) or ""))
        elif tag in FORMAT_CHANGES:
            tracked.append(TrackedChange("format", "", el.get(qn("w:author")) or ""))
    for cid in open_comments:  # a comment running on into later paragraphs
        anchors[cid] = (index, "".join(open_comments[cid]))
    style = p.style.name if p.style is not None else ""
    para = DocParagraph(
        index=index,
        text="".join(final).strip(),
        before_tracking="".join(before).strip(),
        marks=marks,
        item_ref=item_ref,
        is_heading=bool(style) and style.lower().startswith("heading"),
        tracked=tracked,
    )
    return para, anchors


def _row(
    index: int, cells: Any, item_refs: dict[str, str]
) -> tuple[DocParagraph, dict[str, tuple[int, str]]]:
    """A table row as one line; merged cells, which repeat across the row, count once."""
    seen, texts, befores = set(), [], []
    marks: list[int] = []
    tracked: list[TrackedChange] = []
    anchors: dict[str, tuple[int, str]] = {}
    for cell in cells:
        if id(cell._tc) in seen:
            continue
        seen.add(id(cell._tc))
        parts, before = [], []
        for p in cell.paragraphs:
            para, found = _paragraph(index, p, item_refs)
            parts.append(para.text)
            before.append(para.before_tracking)
            marks += para.marks
            tracked += para.tracked
            anchors.update(found)
        texts.append("\n".join(parts).strip())
        befores.append("\n".join(before).strip())
    row = DocParagraph(
        index=index,
        text=" | ".join(texts).strip(),
        before_tracking=" | ".join(befores).strip(),
        marks=marks,
        item_ref=None,
        is_heading=False,
        tracked=tracked,
        in_table=True,
    )
    return row, anchors


def _comments(doc: Document, anchors: dict[str, tuple[int, str]]) -> list[DocComment]:
    """Comments with their anchors; replies point at the comment they answer."""
    part = _related(doc, RT.COMMENTS)
    if part is None:
        return []
    root = parse_xml(part.blob)
    by_para_id: dict[str, str] = {}
    found = []
    for c in root.iter(qn("w:comment")):
        cid = c.get(qn("w:id")) or ""
        paras = list(c.iter(qn("w:p")))
        if paras and (pid := paras[-1].get(f"{{{W14}}}paraId")):
            by_para_id[pid] = cid
        text = "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in paras).strip()
        found.append((cid, c.get(qn("w:author")) or "", text))

    parents: dict[str, str] = {}
    extended = _related(
        doc, "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
    )
    if extended is not None:
        for ex in parse_xml(extended.blob).iter(f"{{{W15}}}commentEx"):
            child = by_para_id.get(ex.get(f"{{{W15}}}paraId") or "")
            parent = by_para_id.get(ex.get(f"{{{W15}}}paraIdParent") or "")
            if child and parent:
                parents[child] = parent

    out = []
    for cid, author, text in found:
        index, anchor = anchors.get(cid, (None, ""))
        out.append(DocComment(cid, author, text, index, anchor, parents.get(cid)))
    return out


def _related(doc: Document, reltype: str):  # noqa: ANN202
    for rel in doc.part.rels.values():
        if rel.reltype == reltype and not rel.is_external:
            return rel.target_part
    return None
