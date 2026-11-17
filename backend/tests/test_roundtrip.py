import io

import docx
import pytest
from docx.document import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from app.minutes.docx_export import render_minutes_docx
from app.minutes.profile_content import PresentationSettings
from app.minutes.roundtrip import ChangeStatus, WrongDraftError, compare_final
from tests import minutes_samples as samples

SETTINGS = PresentationSettings()


def exported(run_id: str = "run-1") -> Document:
    data = render_minutes_docx(samples.draft(), SETTINGS, run_id=run_id)
    return docx.Document(io.BytesIO(data))


def saved(doc: Document) -> bytes:
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def paragraph(doc: Document, starts: str):  # noqa: ANN201
    return next(p for p in doc.paragraphs if p.text.startswith(starts))


def tracked(kind: str, text: str) -> object:
    """A tracked insertion (w:ins) or deletion (w:del) run, as Word writes them."""
    tag = "w:t" if kind == "ins" else "w:delText"
    return parse_xml(
        f'<w:{kind} {nsdecls("w")} w:id="7{len(text)}" w:author="Jane">'
        f'<w:r><{tag} xml:space="preserve">{text}</{tag}></w:r></w:{kind}>'
    )


def test_untouched_download_is_unchanged() -> None:
    result = compare_final(saved(exported()), samples.draft(), "run-1", SETTINGS)

    assert result.run_id == "run-1"
    assert {c.status for c in result.items} == {ChangeStatus.UNCHANGED}
    assert result.similarity == 1.0
    assert result.comments == []  # our own question comments are not reviewer comments


def test_edits_are_compared_item_by_item() -> None:
    doc = exported()
    roof = paragraph(doc, "The Board approved phase one only")
    roof.add_run(" Priya Shah abstained.")
    report = paragraph(doc, "The Board noted the report.")
    report._p.append(tracked("ins", " and thanked the Chief Executive"))
    report._p.append(tracked("del", " old wording"))
    for p in [paragraph(doc, "5 Any other business"), paragraph(doc, "There was no other")]:
        p._p.getparent().remove(p._p)
    doc.add_paragraph("Matters arising", style="Heading 1")
    doc.add_paragraph("The Board reviewed the action log.")
    doc.add_comment(runs=[roof.runs[0]], text="Check the cap.", author="Jane", initials="J")

    result = compare_final(saved(doc), samples.draft(), "run-1", SETTINGS)

    status = {c.item_ref: c.status for c in result.items}
    assert status == {
        "header": ChangeStatus.UNCHANGED,
        "1": ChangeStatus.UNCHANGED,
        "2": ChangeStatus.UNCHANGED,
        "3": ChangeStatus.EDITED,
        "4": ChangeStatus.EDITED,
        "5": ChangeStatus.DELETED,
        "added-1": ChangeStatus.ADDED,
    }
    item3 = next(c for c in result.items if c.item_ref == "3")
    assert item3.final_text == "The Board noted the report. and thanked the Chief Executive"
    assert item3.words_added == 5 and item3.words_removed == 0
    added = result.items[-1]
    assert added.heading == "Matters arising"
    assert added.final_text == "The Board reviewed the action log."
    assert [(c.author, c.text) for c in result.comments] == [("Jane", "Check the cap.")]
    assert 0 < result.similarity < 1


def test_heading_without_its_bookmark_is_matched_by_text() -> None:
    doc = exported()
    for b in list(doc.element.body.iter(qn("w:bookmarkStart"))):
        b.getparent().remove(b)
    paragraph(doc, "The Board noted the report.").add_run(" Questions were taken.")

    result = compare_final(saved(doc), samples.draft(), "run-1", SETTINGS)

    status = {c.item_ref: c.status for c in result.items}
    assert status["3"] == ChangeStatus.EDITED
    assert status["4"] == ChangeStatus.UNCHANGED


def test_paragraph_numbers_are_not_counted_as_edits() -> None:
    numbered = SETTINGS.model_copy(update={"paragraph_numbering": "item_decimal"})
    data = render_minutes_docx(samples.draft(), numbered, run_id="run-1")

    result = compare_final(data, samples.draft(), "run-1", numbered)

    assert {c.status for c in result.items} == {ChangeStatus.UNCHANGED}


def test_file_from_another_draft_is_rejected() -> None:
    with pytest.raises(WrongDraftError):
        compare_final(saved(exported("run-2")), samples.draft(), "run-1", SETTINGS)


def test_file_without_an_id_is_still_compared() -> None:
    doc = exported()
    doc.core_properties.identifier = ""
    result = compare_final(saved(doc), samples.draft(), "run-1", SETTINGS)
    assert result.run_id is None
    assert result.similarity == 1.0
