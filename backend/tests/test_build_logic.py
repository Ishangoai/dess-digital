from pathlib import Path

import docx

from app.minutes.build_logic import main


def write_docx(path: Path, title: str, heading: str, body: str) -> Path:
    document = docx.Document()
    document.add_paragraph(title, style="Title")
    document.add_heading(heading, level=1)
    document.add_paragraph(body)
    document.save(str(path))
    return path


def test_build_logic_joins_both_documents_verbatim(tmp_path: Path) -> None:
    standards = write_docx(tmp_path / "s.docx", "Standards", "MP1 Context", "Record the body.")
    logic = write_docx(tmp_path / "l.docx", "Operating logic", "Stage 1", "Read the agenda first.")
    out = tmp_path / "out" / "logic.md"

    assert main([str(standards), str(logic), "--out", str(out)]) == 0

    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Minuting logic")
    assert text.index("# Part A: Professional Standards") < text.index("# Part B: Operational")
    assert "## Standards\n\n### MP1 Context\n\nRecord the body." in text
    assert "### Stage 1\n\nRead the agenda first." in text
