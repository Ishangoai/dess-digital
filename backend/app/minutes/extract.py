"""Plain text from uploaded meeting files."""

import io
from pathlib import Path
from typing import Any

import docx
from docx.document import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

TEXT_SUFFIXES = {".txt", ".md", ".vtt"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".docx"}


class UnsupportedFileError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        text = _decode(data)
    elif suffix == ".docx":
        text = _docx_text(data)
    else:
        allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise UnsupportedFileError(f"{filename}: unsupported file type (use {allowed})")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _docx_text(data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises several unrelated types for bad files
        raise UnsupportedFileError(f"not a readable .docx file: {e}") from e
    numbering = _ListNumbering(document)
    lines: list[str] = []
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(block, document)
            text = paragraph.text.strip()
            if text:
                lines.append(numbering.label(paragraph) + text)
        elif tag == "tbl":
            for row in Table(block, document).rows:
                cells: list[str] = []
                for cell in row.cells:
                    value = " / ".join(cell.text.split("\n")).strip()
                    if value and (not cells or cells[-1] != value):  # merged cells repeat
                        cells.append(value)
                if cells:
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


class _ListNumbering:
    """Rebuilds Word's automatic list numbers, which paragraph.text leaves out."""

    def __init__(self, document: Document) -> None:
        try:
            self._numbering: Any = document.part.numbering_part.element
        except (KeyError, NotImplementedError):
            self._numbering = None
        self._counters: dict[str, list[int]] = {}

    def label(self, paragraph: Paragraph) -> str:
        found = self._num_pr(paragraph)
        if found is None or self._numbering is None:
            return ""
        num_id, level = found
        levels = self._levels(num_id)
        if not levels or level >= len(levels):
            return ""
        counters = self._counters.setdefault(num_id, [lvl["start"] - 1 for lvl in levels])
        counters[level] += 1
        for deeper in range(level + 1, len(counters)):
            counters[deeper] = levels[deeper]["start"] - 1
        fmt, text = levels[level]["fmt"], levels[level]["text"]
        if fmt == "bullet":
            return "- "
        if fmt == "none":
            return ""
        for i in range(len(levels)):
            text = text.replace(f"%{i + 1}", _format(max(counters[i], 1), levels[i]["fmt"]))
        return f"{text} " if text else ""

    def _num_pr(self, paragraph: Paragraph) -> tuple[str, int] | None:
        # Numbering is set on the paragraph or inherited from its style chain.
        elements: list[Any] = [paragraph._p]
        style = paragraph.style
        while style is not None:
            elements.append(style.element)
            style = style.base_style
        for element in elements:
            num_ids = element.xpath("./w:pPr/w:numPr/w:numId/@w:val")
            if num_ids:
                if num_ids[0] == "0":  # numbering explicitly removed
                    return None
                levels = element.xpath("./w:pPr/w:numPr/w:ilvl/@w:val")
                return str(num_ids[0]), int(levels[0]) if levels else 0
        return None

    def _levels(self, num_id: str) -> list[dict[str, Any]]:
        abstract_ids = self._numbering.xpath(f'./w:num[@w:numId="{num_id}"]/w:abstractNumId/@w:val')
        if not abstract_ids:
            return []
        lvls = self._numbering.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract_ids[0]}"]/w:lvl')
        levels = []
        for lvl in sorted(lvls, key=lambda e: int(e.get(qn("w:ilvl"), "0"))):
            start = _child_val(lvl, "w:start")
            levels.append(
                {
                    "start": int(start) if start else 1,
                    "fmt": _child_val(lvl, "w:numFmt") or "decimal",
                    "text": _child_val(lvl, "w:lvlText") or "",
                }
            )
        return levels


def _child_val(element: Any, tag: str) -> str | None:
    child = element.find(qn(tag))
    return child.get(qn("w:val")) if child is not None else None


def _format(n: int, fmt: str) -> str:
    if fmt in {"lowerLetter", "upperLetter"}:
        letters = ""
        while n > 0:
            n, rem = divmod(n - 1, 26)
            letters = chr(ord("a") + rem) + letters
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in {"lowerRoman", "upperRoman"}:
        roman = _roman(n)
        return roman.lower() if fmt == "lowerRoman" else roman
    return str(n)


def _roman(n: int) -> str:
    values = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]  # fmt: skip
    out = ""
    for value, numeral in values:
        while n >= value:
            out += numeral
            n -= value
    return out
