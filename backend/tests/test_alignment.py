"""DESS-050: an edited Word copy is read back and lined up with the exact original."""

import io

import docx
from docx.document import Document
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.text.paragraph import Paragraph

from app.minutes.alignment import Alignment, align, word_diff
from app.minutes.docx_export import RenderedDocx, bookmark_name, render_for_review
from app.minutes.docx_read import W14, W15, read_docx
from app.minutes.llm_schemas import ActionEntry
from app.minutes.profile_content import PresentationSettings
from app.minutes.roundtrip import summarise
from tests import minutes_samples as samples

SETTINGS = PresentationSettings()
DRAFT = samples.draft()
ITEM_REFS = {bookmark_name(i.item_ref): i.item_ref for i in DRAFT.items}


def exported() -> tuple[RenderedDocx, Document]:
    rendered = render_for_review(DRAFT, SETTINGS, run_id="run-1", export_id="exp-1")
    return rendered, docx.Document(io.BytesIO(rendered.data))


def saved(doc: Document) -> bytes:
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def lined_up(rendered: RenderedDocx, doc: Document) -> Alignment:
    original = read_docx(rendered.data, ITEM_REFS)
    return align(original, rendered.marks, read_docx(saved(doc), ITEM_REFS))


def para(doc: Document, starts: str) -> Paragraph:
    return next(p for p in doc.paragraphs if p.text.startswith(starts))


def statuses(alignment: Alignment) -> dict[str, str]:
    return {r.original_text or r.final_text: r.status for r in alignment.paragraphs}


def tracked(kind: str, text: str) -> object:
    """A tracked insertion (w:ins) or deletion (w:del), as Word writes them."""
    tag = "w:t" if kind == "ins" else "w:delText"
    return parse_xml(
        f'<w:{kind} {nsdecls("w")} w:id="7{len(text)}" w:author="Jane">'
        f'<w:r><{tag} xml:space="preserve">{text}</{tag}></w:r></w:{kind}>'
    )


def test_the_export_carries_its_ids() -> None:
    rendered, _ = exported()
    original = read_docx(rendered.data, ITEM_REFS)

    assert (original.run_id, original.export_id) == ("run-1", "exp-1")
    assert all(len(p.marks) == 1 for p in original.paragraphs)
    roof = next(m for m in rendered.marks if m.paragraph_id == "4.p2")
    assert (roof.section, roof.role) == ("4", "body")
    assert roof.text.startswith("The Board approved phase one only")


def test_an_untouched_copy_is_unchanged() -> None:
    rendered, doc = exported()
    alignment = lined_up(rendered, doc)

    assert {r.status for r in alignment.paragraphs} == {"unchanged"}
    assert summarise(alignment, [], "run-1").similarity == 1.0


def test_edits_without_track_changes() -> None:
    rendered, doc = exported()
    para(doc, "The Board approved phase one only").add_run(" Priya Shah abstained.")
    gone = para(doc, "There was no other business.")
    gone._p.getparent().remove(gone._p)
    para(doc, "The Board noted the report.").insert_paragraph_before("Questions were taken.")

    alignment = lined_up(rendered, doc)

    s = statuses(alignment)
    assert s["The Board approved phase one only, capped at £1.2 million."] == "changed"
    assert s["There was no other business."] == "removed"
    assert s["Questions were taken."] == "added"
    assert s["The Board noted the report."] == "unchanged"
    changed = next(r for r in alignment.paragraphs if r.status == "changed")
    inserted = "".join(d.text for d in changed.diff if d.op == "insert")
    assert "Priya Shah abstained" in inserted
    assert not [d for d in changed.diff if d.op == "delete"]
    added = next(r for r in alignment.paragraphs if r.status == "added")
    assert added.item_ref == "3"
    removed = next(r for r in alignment.paragraphs if r.status == "removed")
    assert removed.item_ref == "5"


def test_edits_with_track_changes_on() -> None:
    rendered, doc = exported()
    report = para(doc, "The Board noted the report.")
    report._p.append(tracked("ins", " and thanked the Chief Executive"))
    report._p.append(tracked("del", " old wording"))

    alignment = lined_up(rendered, doc)

    row = next(r for r in alignment.paragraphs if r.paragraph_id == "3.p1")
    assert row.status == "changed"
    assert row.final_text == "The Board noted the report. and thanked the Chief Executive"
    assert [(t.kind, t.text, t.author) for t in row.tracked] == [
        ("insert", " and thanked the Chief Executive", "Jane"),
        ("delete", " old wording", "Jane"),
    ]


def test_a_paragraph_moved_to_another_item() -> None:
    rendered, doc = exported()
    moved = para(doc, "Priya Shah remained concerned")
    para(doc, "The Board noted the report.")._p.addnext(moved._p)  # bookmark travels with it

    alignment = lined_up(rendered, doc)

    row = next(r for r in alignment.paragraphs if r.paragraph_id == "4.p1")
    assert (row.status, row.original_item_ref, row.item_ref) == ("moved", "4", "3")


def test_a_moved_paragraph_that_lost_its_id_is_found_by_text() -> None:
    rendered, doc = exported()
    old = para(doc, "Priya Shah remained concerned")
    text = old.text
    old._p.getparent().remove(old._p)
    para(doc, "The Board noted the report.").insert_paragraph_before(text)

    alignment = lined_up(rendered, doc)

    row = next(r for r in alignment.paragraphs if r.paragraph_id == "4.p1")
    assert (row.status, row.item_ref) == ("moved", "3")


def test_a_paragraph_whose_bookmark_was_deleted() -> None:
    rendered, doc = exported()
    roof = para(doc, "The Board approved phase one only")
    for b in list(roof._p.iter(qn("w:bookmarkStart"))):
        b.getparent().remove(b)
    roof.add_run(" Priya Shah abstained.")

    alignment = lined_up(rendered, doc)

    row = next(r for r in alignment.paragraphs if r.paragraph_id == "4.p2")
    assert row.status == "changed"
    assert row.final_text.endswith("Priya Shah abstained.")


def test_a_heading_that_lost_its_bookmarks_is_matched_by_text() -> None:
    rendered, doc = exported()
    heading = para(doc, "3 Chief Executive")
    for b in list(heading._p.iter(qn("w:bookmarkStart"))):
        b.getparent().remove(b)

    alignment = lined_up(rendered, doc)

    assert next(r for r in alignment.paragraphs if r.paragraph_id == "3.p1").item_ref == "3"
    assert [s.item_ref for s in alignment.sections] == ["header", "1", "2", "3", "4", "5"]


def test_a_reply_to_a_question_is_linked_to_it() -> None:
    rendered, doc = exported()
    roof = para(doc, "The Board approved phase one only")
    doc.add_comment(runs=[roof.runs[-1]], text="The Company Secretary will write.", author="Jane")
    _link_reply(doc, reply_index=-1, parent_index=0)

    final = read_docx(saved(doc), ITEM_REFS)

    question, reply = final.comments[0], final.comments[-1]
    assert question.author == SETTINGS.comment_author
    assert question.anchor == "phase one only"
    assert reply.parent_id == question.id
    assert reply.text == "The Company Secretary will write."


def retyped(heading_style: str | None) -> Document:
    """The draft retyped into a brand-new document: no hidden ids, no file id."""
    doc = docx.Document()
    for item in DRAFT.items:
        heading = doc.add_paragraph(f"{item.item_ref}. {item.heading}")
        if heading_style:
            heading.style = heading_style
        else:
            heading.runs[0].bold = True  # a heading typed as bold text
        for paragraph in item.paragraphs:
            doc.add_paragraph(paragraph.text)
    return doc


def test_a_new_document_with_bold_text_headings() -> None:
    rendered, _ = exported()
    doc = retyped(heading_style=None)
    para(doc, "The Board noted the report.").runs[
        0
    ].text = "The Board noted the report with thanks."

    alignment = lined_up(rendered, doc)

    report = next(r for r in alignment.paragraphs if r.paragraph_id == "3.p1")
    assert (report.status, report.item_ref) == ("changed", "3")
    roof = next(r for r in alignment.paragraphs if r.paragraph_id == "4.p1")
    assert (roof.status, roof.item_ref) == ("unchanged", "4")
    assert not [s for s in alignment.sections if s.added]


def test_a_paragraph_rewritten_in_place_is_changed_not_removed_and_added() -> None:
    rendered, _ = exported()
    doc = retyped(heading_style="Heading 1")
    concern = para(doc, "Priya Shah remained concerned")
    concern.runs[0].text = "One director said the contingency was too thin for this programme."

    alignment = lined_up(rendered, doc)

    row = next(r for r in alignment.paragraphs if r.paragraph_id == "4.p1")
    assert row.status == "changed"
    assert row.final_text.startswith("One director said the contingency")
    items = [r for r in alignment.paragraphs if r.item_ref != "header"]  # header not retyped
    assert not [r for r in items if r.status in ("added", "removed")]


def test_a_rewrite_followed_by_new_paragraphs_is_still_matched() -> None:
    rendered, _ = exported()
    doc = retyped(heading_style="Heading 1")
    roof = para(doc, "The Board approved phase one only")
    roof.runs[0].text = "It was resolved that phase one only be approved, capped at £1.2 million."
    for text in ["Action: the Finance Director to sign.", "Action: tenants to be told."]:
        new = doc.add_paragraph(text)
        roof._p.addnext(new._p)

    alignment = lined_up(rendered, doc)

    row = next(r for r in alignment.paragraphs if r.paragraph_id == "4.p2")
    assert row.status == "changed" and row.final_text.startswith("It was resolved")
    added = [r.final_text for r in alignment.paragraphs if r.status == "added"]
    assert sorted(added) == ["Action: tenants to be told.", "Action: the Finance Director to sign."]


def test_the_actions_table_is_compared_row_by_row() -> None:
    draft = DRAFT.model_copy(deep=True)
    draft.actions = [
        ActionEntry(
            action_id="4.AC1",
            text="Write to tenants about the roof works",
            owner=None,
            due=None,
            paragraph_id="4.p2",
        ),
    ]
    settings = SETTINGS.model_copy(update={"action_presentation": "inline_and_table"})
    rendered = render_for_review(draft, settings, run_id="run-1", export_id="exp-1")
    doc = docx.Document(io.BytesIO(rendered.data))
    table = doc.tables[0]
    table.rows[1].cells[1].text = "Company Secretary"
    added = table.add_row().cells
    added[0].text, added[1].text = "Brief the auditors on the contract", "Finance Director"

    alignment = lined_up(rendered, doc)

    rows = [r for r in alignment.paragraphs if r.item_ref == "actions" and r.role != "heading"]
    assert [(r.status, r.final_text) for r in rows] == [
        ("unchanged", "Action | Owner | Due"),
        ("changed", "Write to tenants about the roof works | Company Secretary |"),
        ("added", "Brief the auditors on the contract | Finance Director |"),
    ]
    assert rows[1].role == "action"
    summary = summarise(alignment, [], "run-1")
    assert next(i for i in summary.items if i.item_ref == "actions").status == "edited"


def test_word_diff_keeps_spaces_and_punctuation() -> None:
    assert [(s.op, s.text) for s in word_diff("The Board approved it.", "It was resolved.")] == [
        ("delete", "The Board approved it"),
        ("insert", "It was resolved"),
        ("equal", "."),
    ]


def _link_reply(doc: Document, reply_index: int, parent_index: int) -> None:
    """Mark one comment as a reply to another, the way Word does (commentsExtended.xml)."""
    rel = next(r for r in doc.part.rels.values() if r.reltype.endswith("/comments"))
    comments = list(rel.target_part.element.iter(qn("w:comment")))
    ids = []
    for n, c in enumerate(comments):
        p = list(c.iter(qn("w:p")))[-1]
        p.set(f"{{{W14}}}paraId", f"0000{n:04X}")
        ids.append(f"0000{n:04X}")
    xml = (
        f'<w15:commentsEx xmlns:w15="{W15}">'
        f'<w15:commentEx w15:paraId="{ids[parent_index]}"/>'
        f'<w15:commentEx w15:paraId="{ids[reply_index]}" w15:paraIdParent="{ids[parent_index]}"/>'
        "</w15:commentsEx>"
    )
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
    )
    part = Part(PackURI("/word/commentsExtended.xml"), content_type, xml.encode(), doc.part.package)
    doc.part.relate_to(
        part, "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
    )
