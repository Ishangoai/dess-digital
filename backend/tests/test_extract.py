import io

import docx
import pytest

from app.minutes.extract import UnsupportedFileError, docx_to_markdown, extract_text


def docx_bytes(build) -> bytes:
    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_plain_text_with_bom_and_crlf() -> None:
    data = "﻿1. Apologies\r\n2. Minutes\r\n".encode()
    assert extract_text("agenda.txt", data) == "1. Apologies\n2. Minutes"


def test_cp1252_fallback() -> None:
    assert extract_text("notes.md", "Budget £5m".encode("cp1252")) == "Budget £5m"


def test_docx_restores_list_numbers_and_reads_tables() -> None:
    def build(d) -> None:
        d.add_paragraph("Board agenda")
        d.add_paragraph("Apologies", style="List Number")
        d.add_paragraph("Roof contract (for approval)", style="List Number")
        table = d.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Paper"
        table.cell(0, 1).text = "B/26/04"

    text = extract_text("agenda.docx", docx_bytes(build))
    assert text.split("\n") == [
        "Board agenda",
        "1. Apologies",
        "2. Roof contract (for approval)",
        "Paper | B/26/04",
    ]


def test_unsupported_type() -> None:
    with pytest.raises(UnsupportedFileError):
        extract_text("agenda.pdf", b"%PDF")


def test_corrupt_docx() -> None:
    with pytest.raises(UnsupportedFileError):
        extract_text("agenda.docx", b"not a zip")


def test_docx_to_markdown_keeps_headings_lists_and_tables() -> None:
    def build(d) -> None:
        d.add_paragraph("Minuting standards", style="Title")
        d.add_heading("MP4 Outcomes", level=1)
        d.add_paragraph("Record what was decided.")
        d.add_paragraph("Never infer approval", style="List Bullet")
        d.add_paragraph("Keep conditions", style="List Bullet")
        table = d.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Outcome"
        table.cell(0, 1).text = "Meaning"
        table.cell(1, 0).text = "noted"
        table.cell(1, 1).text = "received | no decision"

    markdown = docx_to_markdown(docx_bytes(build), heading_offset=1)
    assert markdown.split("\n\n") == [
        "## Minuting standards",
        "### MP4 Outcomes",
        "Record what was decided.",
        "- Never infer approval\n- Keep conditions",
        "| Outcome | Meaning |\n| --- | --- |\n| noted | received \| no decision |\n",
    ]
