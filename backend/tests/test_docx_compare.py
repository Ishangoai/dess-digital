"""Reading an edited copy of the export and lining it up with the original. Invented text only."""

import copy
import io
from collections.abc import Callable
from typing import Any

import docx
import pytest
from docx.document import Document
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml.ns import nsdecls, qn
from docx.oxml.parser import parse_xml

from app.minutes.docx_compare import (
    COMMENTS_EXTENDED_RT,
    W14,
    W15,
    Comparison,
    ParagraphChange,
    compare,
    read_docx,
)
from app.minutes.docx_export import (
    MARKER,
    ExportManifest,
    bookmark_name,
    render_minutes,
)
from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import ActionEntry
from app.minutes.profile_content import ActionPresentation, PresentationSettings
from tests import minutes_samples as samples

AUTHOR = "Company Secretary"
WHEN = "2026-03-13T09:00:00Z"


def export(draft=None, template: bytes | None = None, **settings) -> tuple[bytes, ExportManifest]:
    rendered = render_minutes(
        draft or samples.draft(),
        PresentationSettings(**settings),
        template,
        identifier="dess-export:test",
    )
    return rendered.data, rendered.manifest


def edit(data: bytes, change: Callable[[Document], None]) -> bytes:
    doc = docx.Document(io.BytesIO(data))
    change(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def run_compare(original: bytes, edited: bytes, manifest: ExportManifest) -> Comparison:
    before = read_docx(original, manifest)
    hints = [(b.heading_key, b.text) for b in before.blocks if b.heading_key]
    return compare(before, read_docx(edited, manifest, heading_hints=hints), manifest)


def para(doc: Document, paragraph_id: str) -> Any:
    name = bookmark_name(paragraph_id)
    start = next(
        b for b in doc.element.body.iter(qn("w:bookmarkStart")) if b.get(qn("w:name")) == name
    )
    return start.getparent()


def set_runs(p: Any, xml: str) -> None:
    """Replace a paragraph's runs with raw WordprocessingML (for tracked changes)."""
    for r in p.findall(qn("w:r")):
        p.remove(r)
    end = p.find(qn("w:bookmarkEnd"))
    for el in parse_xml(f"<w:root {nsdecls('w')}>{xml}</w:root>"):
        end.addprevious(el)


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def change_for(comparison: Comparison, paragraph_id: str) -> ParagraphChange:
    return next(c for s in comparison.sections for c in s.changes if c.paragraph_id == paragraph_id)


def statuses(comparison: Comparison) -> dict[str, int]:
    return {k: v for k, v in comparison.counts.items() if v}


# the export


def test_every_minute_paragraph_and_heading_is_bookmarked() -> None:
    data, manifest = export()
    doc = docx.Document(io.BytesIO(data))
    names = {b.get(qn("w:name")) for b in doc.element.body.iter(qn("w:bookmarkStart"))}

    paragraph_ids = [p.paragraph_id for i in samples.draft().items for p in i.paragraphs]
    assert set(manifest.paragraphs.values()) == set(paragraph_ids)
    assert set(manifest.headings.values()) == {"1", "2", "3", "4", "5"}
    assert names == set(manifest.paragraphs) | set(manifest.headings)
    assert "dess_4_p2" in names
    assert para(doc, "4.p2").xpath("string(.)").startswith("The Board approved")
    assert manifest.questions == {"0": "Q1"}
    assert doc.core_properties.identifier == "dess-export:test"


def test_bookmarks_survive_in_a_template_export() -> None:
    template = docx.Document()
    template.add_paragraph("Letterhead")
    start = template.paragraphs[0]._p
    start.insert(0, parse_xml(f'<w:bookmarkStart {nsdecls("w")} w:id="7" w:name="logo"/>'))
    template.add_paragraph(MARKER)
    buffer = io.BytesIO()
    template.save(buffer)

    data, manifest = export(template=buffer.getvalue())
    doc = docx.Document(io.BytesIO(data))
    ids = [b.get(qn("w:id")) for b in doc.element.body.iter(qn("w:bookmarkStart"))]
    assert len(ids) == len(set(ids))  # no clash with the template's own bookmark
    assert para(doc, "4.p2") is not None
    assert len(manifest.paragraphs) == 7


def test_long_ids_give_valid_bookmark_names() -> None:
    assert bookmark_name("4.1.p2") == "dess_4_1_p2"
    long = bookmark_name("AB12.sub.item.with.a.very.long.reference.p10")
    assert len(long) <= 40 and long.startswith("dess_")


# reading and comparing


def test_unedited_copy_is_all_unchanged() -> None:
    data, manifest = export()
    result = run_compare(data, edit(data, lambda doc: None), manifest)

    assert statuses(result) == {"unchanged": result.counts["unchanged"]}
    assert result.bookmarks_found == result.bookmarks_expected == 7
    assert [s.section for s in result.sections] == ["header", "1", "2", "3", "4", "5"]
    assert result.sections[4].heading == "4 Roof replacement programme: contract award"


def test_tracked_changes_are_accepted() -> None:
    data, manifest = export()

    def track(doc: Document) -> None:
        set_runs(
            para(doc, "4.p1"),
            f'<w:del w:id="901" w:author="{AUTHOR}" w:date="{WHEN}">'
            "<w:r><w:delText>Priya Shah</w:delText></w:r></w:del>"
            f'<w:ins w:id="902" w:author="{AUTHOR}" w:date="{WHEN}">{run("One trustee")}</w:ins>'
            + run(" remained concerned that the 5% contingency was thin."),
        )

    edited = edit(data, track)
    result = run_compare(data, edited, manifest)
    change = change_for(result, "4.p1")

    assert change.status == "changed"
    assert change.matched_by == "bookmark"
    assert change.edited == "One trustee remained concerned that the 5% contingency was thin."
    assert [(t.kind, t.text, t.author) for t in change.tracked_changes] == [
        ("deletion", "Priya Shah", AUTHOR),
        ("insertion", "One trustee", AUTHOR),
    ]
    assert [(d.op, d.text) for d in change.diff][:3] == [
        ("delete", "Priya Shah"),
        ("insert", "One trustee"),
        ("equal", "remained concerned that the 5% contingency was thin."),
    ]
    assert result.tracked_change_authors == [AUTHOR]
    # python-docx's own text drops the insertion, which is why the XML is read directly.
    reread = docx.Document(io.BytesIO(edited))
    assert not any(p.text.startswith("One trustee") for p in reread.paragraphs)


def test_untracked_edit() -> None:
    data, manifest = export()

    def retype(doc: Document) -> None:
        set_runs(para(doc, "3.p1"), run("The Board noted the report and thanked the team."))

    result = run_compare(data, edit(data, retype), manifest)
    change = change_for(result, "3.p1")
    assert change.status == "changed"
    assert change.tracked_changes == []
    assert statuses(result) == {"unchanged": result.counts["unchanged"], "changed": 1}


def test_whitespace_only_is_unchanged_but_flagged() -> None:
    data, manifest = export()

    def spaces(doc: Document) -> None:
        set_runs(para(doc, "3.p1"), run("The Board  noted the report."))

    change = change_for(run_compare(data, edit(data, spaces), manifest), "3.p1")
    assert change.status == "unchanged"
    assert change.format_only


def test_moved_paragraph() -> None:
    data, manifest = export()

    def move(doc: Document) -> None:
        para(doc, "3.p1").addnext(para(doc, "1.p2"))

    result = run_compare(data, edit(data, move), manifest)
    change = change_for(result, "1.p2")
    assert change.status == "moved"
    assert (change.from_section, change.section) == ("1", "3")
    assert not change.text_changed
    assert result.counts["moved"] == 1


def test_reordered_within_an_item() -> None:
    data, manifest = export()

    def swap(doc: Document) -> None:
        para(doc, "4.p2").addnext(para(doc, "4.p1"))

    result = run_compare(data, edit(data, swap), manifest)
    moved = [c for s in result.sections for c in s.changes if c.status == "moved"]
    assert len(moved) == 1 and moved[0].from_section is None


def test_deleted_bookmark_falls_back_to_text() -> None:
    data, manifest = export()

    def lose_bookmark(doc: Document) -> None:
        p = para(doc, "4.p1")
        for tag in ("w:bookmarkStart", "w:bookmarkEnd"):
            p.remove(p.find(qn(tag)))
        for r in p.findall(qn("w:r")):
            p.remove(r)
        p.append(parse_xml(f"<w:r {nsdecls('w')}><w:t>Priya Shah remained concerned that "
                           "the 5% contingency was too thin.</w:t></w:r>"))  # fmt: skip

    result = run_compare(data, edit(data, lose_bookmark), manifest)
    change = change_for(result, "4.p1")
    assert change.status == "changed"
    assert change.matched_by == "text"
    assert result.bookmarks_found == 6


def test_removed_and_added_paragraphs() -> None:
    data, manifest = export()

    def rewrite(doc: Document) -> None:
        p = para(doc, "5.p1")
        p.getparent().remove(p)
        new = copy.deepcopy(para(doc, "3.p1"))
        for tag in ("w:bookmarkStart", "w:bookmarkEnd"):
            new.remove(new.find(qn(tag)))
        for r in new.findall(qn("w:r")):
            new.remove(r)
        new.append(parse_xml(f"<w:r {nsdecls('w')}><w:t>A report on damp was requested for "
                             "May.</w:t></w:r>"))  # fmt: skip
        para(doc, "3.p1").addnext(new)

    result = run_compare(data, edit(data, rewrite), manifest)
    removed = change_for(result, "5.p1")
    assert (removed.status, removed.section) == ("removed", "5")
    added = [c for s in result.sections for c in s.changes if c.status == "added"]
    assert [(a.section, a.edited) for a in added] == [
        ("3", "A report on damp was requested for May.")
    ]


def test_deleted_paragraph_mark_joins_paragraphs() -> None:
    data, manifest = export()

    def join(doc: Document) -> None:
        p = para(doc, "1.p1")
        p_pr = p.find(qn("w:pPr"))
        if p_pr is None:
            p_pr = parse_xml(f"<w:pPr {nsdecls('w')}/>")
            p.insert(0, p_pr)
        p_pr.append(
            parse_xml(
                f'<w:rPr {nsdecls("w")}><w:del w:id="903" w:author="{AUTHOR}" '
                f'w:date="{WHEN}"/></w:rPr>'
            )
        )

    result = run_compare(data, edit(data, join), manifest)
    item = next(s for s in result.sections if s.section == "1")
    assert item.counts["removed"] == 1
    joined = next(c for c in item.changes if c.edited and not c.heading)
    assert joined.edited == (
        "Apologies were received from Daniel."
        "Tom Reid declared an interest in item 4 and left for that item."
    )


def test_actions_table_rows_are_compared() -> None:
    draft = samples.draft()
    draft.actions = [
        ActionEntry(action_id="AC1", text="Report on phase two", owner=None, due=None,
                    paragraph_id="4.p2")
    ]  # fmt: skip
    data, manifest = export(draft, action_presentation=ActionPresentation.INLINE_AND_TABLE)

    def add_action(doc: Document) -> None:
        row = doc.tables[0].add_row().cells
        row[0].text, row[1].text, row[2].text = "Write to tenants", "Sam Hale", "31 March 2026"

    result = run_compare(data, edit(data, add_action), manifest)
    actions = next(s for s in result.sections if s.section == "actions")
    assert [c.edited for c in actions.changes if c.status == "added"] == [
        "Write to tenants | Sam Hale | 31 March 2026"
    ]


def add_reply(doc: Document, reply: str, renumber: bool = False) -> None:
    """Reply to the question comment the way Word does, via commentsExtended.xml."""
    part = next(r.target_part for r in doc.part.rels.values() if r.reltype.endswith("/comments"))
    root = part.element
    question = root.find(qn("w:comment"))
    question.findall(qn("w:p"))[-1].set(f"{{{W14}}}paraId", "1A2B3C4D")
    if renumber:  # Word may renumber comment ids when it saves
        for el in doc.element.body.iter(
            qn("w:commentRangeStart"), qn("w:commentRangeEnd"), qn("w:commentReference")
        ):
            el.set(qn("w:id"), "7")
        question.set(qn("w:id"), "7")
    root.append(
        parse_xml(
            f'<w:comment {nsdecls("w")} xmlns:w14="{W14}" w:id="8" w:author="{AUTHOR}" '
            f'w:date="{WHEN}"><w:p w14:paraId="5E6F7A8B">{run(reply)}</w:p></w:comment>'
        )
    )
    blob = (
        f'<w15:commentsEx xmlns:w15="{W15}">'
        '<w15:commentEx w15:paraId="1A2B3C4D" w15:done="1"/>'
        '<w15:commentEx w15:paraId="5E6F7A8B" w15:paraIdParent="1A2B3C4D" w15:done="0"/>'
        "</w15:commentsEx>"
    ).encode()
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
    )
    extended = Part(PackURI("/word/commentsExtended.xml"), content_type, blob, doc.part.package)
    doc.part.relate_to(extended, COMMENTS_EXTENDED_RT)


@pytest.mark.parametrize("renumber", [False, True])
def test_reply_to_a_question_is_linked_to_it(renumber: bool) -> None:
    data, manifest = export()
    edited = edit(data, lambda doc: add_reply(doc, "Sam Hale will write to tenants.", renumber))
    result = run_compare(data, edited, manifest)

    [thread] = result.comments
    assert thread.question_id == "Q1"
    assert thread.resolved
    assert (thread.section, thread.paragraph_id) == ("4", "4.p2")
    assert [(r.author, r.text) for r in thread.replies] == [
        (AUTHOR, "Sam Hale will write to tenants.")
    ]
    assert thread.comment_id in change_for(result, "4.p2").comment_ids


def test_not_a_word_file() -> None:
    with pytest.raises(UnsupportedFileError):
        read_docx(b"not a docx", ExportManifest())
