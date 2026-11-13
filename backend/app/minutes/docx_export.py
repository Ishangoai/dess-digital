"""Draft minutes as an editable Word document, with clarification questions as comments."""

import io
import logging
from datetime import date
from typing import Any

import docx
from docx.document import Document
from docx.shared import Pt
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.minutes.llm_schemas import (
    AnchorKind,
    ClarificationQuestion,
    DraftMinutes,
    MinuteItem,
    MinuteParagraph,
)
from app.minutes.profile_content import (
    ActionPresentation,
    AttendanceLayout,
    DateStyle,
    NumberingScheme,
    ParagraphNumbering,
    PresentationSettings,
)

log = logging.getLogger("app.minutes")

MARKER = "{{MINUTES}}"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def render_minutes_docx(
    draft: DraftMinutes, presentation: PresentationSettings, template: bytes | None = None
) -> bytes:
    writer = _Writer(presentation, template)
    writer.write(draft)
    buffer = io.BytesIO()
    writer.doc.save(buffer)
    return buffer.getvalue()


class _Writer:
    def __init__(self, presentation: PresentationSettings, template: bytes | None) -> None:
        self.p = presentation
        self.doc: Document = docx.Document(io.BytesIO(template)) if template else docx.Document()
        self.marker: Paragraph | None = None
        self.title_runs: list[Run] = []
        self.heading_runs: dict[str, list[Run]] = {}
        if template:
            self.marker = next((p for p in self.doc.paragraphs if p.text.strip() == MARKER), None)
            if self.marker is None:
                self._clear_body()
        elif presentation.font_family or presentation.font_size_pt:
            normal: Any = self.doc.styles["Normal"]
            font = normal.font
            font.name = presentation.font_family or font.name
            if presentation.font_size_pt:
                font.size = Pt(presentation.font_size_pt)

    def write(self, draft: DraftMinutes) -> None:
        h = draft.header
        self.title_runs = self._para(h.title, self.p.styles.title).runs
        if self.p.status_label:
            self._para(self.p.status_label, self.p.styles.body)
        if h.meeting_date:
            self._para(_format_date(h.meeting_date, self.p.date_style), self.p.styles.body)
        if h.time_and_place:
            self._para(h.time_and_place, self.p.styles.body)
        for label, names in (
            ("Present", h.present),
            ("In attendance", h.in_attendance),
            ("Apologies", h.apologies),
        ):
            self._attendance(label, names)

        for index, item in enumerate(draft.items, 1):
            self._item(index, item, draft.questions)

        if self.p.action_presentation == ActionPresentation.INLINE_AND_TABLE and draft.actions:
            self._actions_table(draft)

        self._meeting_level_questions(draft)
        if self.marker is not None:
            self.marker._p.getparent().remove(self.marker._p)

    def _item(self, index: int, item: MinuteItem, questions: list[ClarificationQuestion]) -> None:
        number = self._item_number(index, item.item_ref)
        heading = self._para(f"{number} {item.heading}".strip(), self.p.styles.heading)
        self.heading_runs[item.item_ref] = heading.runs
        for n, paragraph in enumerate(item.paragraphs, 1):
            prefix = (
                f"{number}.{n} "
                if self.p.paragraph_numbering == ParagraphNumbering.ITEM_DECIMAL
                else ""
            )
            anchored = [
                q
                for q in questions
                if q.anchor_kind == AnchorKind.PARAGRAPH
                and q.paragraph_id == paragraph.paragraph_id
            ]
            self._minute_paragraph(prefix, paragraph, anchored, item.item_ref)
        for q in questions:
            if q.anchor_kind == AnchorKind.ITEM_HEADING and q.item_ref == item.item_ref:
                self._comment(heading.runs, q)

    def _minute_paragraph(
        self,
        prefix: str,
        paragraph: MinuteParagraph,
        questions: list[ClarificationQuestion],
        item_ref: str,
    ) -> None:
        text = paragraph.text
        spans: list[tuple[ClarificationQuestion, int, int]] = []
        for q in questions:
            start = text.find(q.anchor_text) if q.anchor_text else -1
            if start < 0:
                log.warning("question %s anchor not found; using item heading", q.question_id)
                self._comment(self.heading_runs.get(item_ref) or self.title_runs, q)
                continue
            spans.append((q, start, start + len(q.anchor_text or "")))

        # Split the text into runs at every anchor boundary so comments cover exact phrases.
        cuts = sorted({0, len(text), *[s for _, s, _ in spans], *[e for _, _, e in spans]})
        para = self._para(prefix, self.p.styles.body)
        runs: list[tuple[int, int, Run]] = []
        for a, b in zip(cuts, cuts[1:], strict=False):
            runs.append((a, b, para.add_run(text[a:b])))
        for q, start, end in spans:
            covered = [run for a, b, run in runs if a >= start and b <= end]
            if covered:
                self._comment(covered, q)

    def _meeting_level_questions(self, draft: DraftMinutes) -> None:
        headings = set(self.heading_runs)
        for q in draft.questions:
            orphan_item = q.anchor_kind == AnchorKind.ITEM_HEADING and q.item_ref not in headings
            if q.anchor_kind == AnchorKind.MEETING_HEADING or orphan_item:
                self._comment(self.title_runs, q)

    def _attendance(self, label: str, names: list[str]) -> None:
        if not names:
            return
        if self.p.attendance_layout == AttendanceLayout.PARAGRAPH:
            para = self._para("", self.p.styles.body)
            para.add_run(f"{label}: ").bold = True
            para.add_run(", ".join(names))
            return
        self._para("", self.p.styles.body).add_run(label).bold = True
        for name in names:
            self._para(name, self.p.styles.body)

    def _actions_table(self, draft: DraftMinutes) -> None:
        self._para("Actions", self.p.styles.heading)
        table = self.doc.add_table(rows=1, cols=3)
        if self.p.styles.table in _style_names(self.doc):
            table.style = self.p.styles.table
        for cell, title in zip(table.rows[0].cells, ("Action", "Owner", "Due"), strict=True):
            cell.text = title
        for a in draft.actions:
            row = table.add_row().cells
            row[0].text, row[1].text, row[2].text = a.text, a.owner or "", a.due or ""
        if self.marker is not None:
            self.marker._p.addprevious(table._tbl)

    def _item_number(self, index: int, item_ref: str) -> str:
        if self.p.numbering == NumberingScheme.SEQUENTIAL:
            return str(index)
        if self.p.numbering == NumberingScheme.MINUTE_REFERENCE:
            return f"{self.p.minute_reference_prefix or ''}{index:02d}"
        return item_ref if not item_ref.startswith("AB") else ""

    def _para(self, text: str, style: str) -> Paragraph:
        para = self.doc.add_paragraph()
        if text:
            para.add_run(text)
        para.style = style if style in _style_names(self.doc) else "Normal"
        if self.marker is not None:
            self.marker._p.addprevious(para._p)
        return para

    def _comment(self, runs: list[Run], q: ClarificationQuestion) -> None:
        if not runs:
            return
        self.doc.add_comment(
            runs=runs,
            text=q.question,
            author=self.p.comment_author,
            initials=self.p.comment_initials,
        )

    def _clear_body(self) -> None:
        body = self.doc.element.body
        for child in list(body):
            if not child.tag.endswith("}sectPr"):  # keep page setup, headers and footers
                body.remove(child)


def _style_names(doc: Document) -> set[str]:
    return {s.name for s in doc.styles if s.name}


def _format_date(value: str, style: DateStyle) -> str:
    """Reformat ISO dates; leave anything else as written."""
    try:
        d = date.fromisoformat(value.strip())
    except ValueError:
        return value
    if style == DateStyle.NUMERIC:
        return d.strftime("%d/%m/%Y")
    if style == DateStyle.ORDINAL:
        suffix = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
        return f"{d.day}{suffix} {d:%B %Y}"
    return f"{d.day} {d:%B %Y}"
