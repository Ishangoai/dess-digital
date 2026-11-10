"""Deterministic checks on the mapping and the draft (no LLM)."""

import re
from dataclasses import dataclass

from app.minutes.evidence import EvidenceBundle
from app.minutes.llm_schemas import (
    AnchorKind,
    Association,
    DraftMinutes,
    EvidenceMap,
    OutcomeType,
    PolicySelection,
)

PLACEHOLDER = re.compile(r"\[[^\]]*\]|\bTBC\b|\bTBD\b|\bXX+\b|\?\?\?|<[^>]+>")
DECISIVE = {OutcomeType.APPROVED, OutcomeType.RESOLVED}


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def validate_mapping(mapping: EvidenceMap, bundle: EvidenceBundle) -> list[str]:
    errors: list[str] = []
    refs = [i.ref for i in mapping.agenda_items]
    keys = [b.key for b in mapping.additional_business]
    for dup in sorted({r for r in refs + keys if (refs + keys).count(r) > 1}):
        errors.append(f"duplicate item ref '{dup}'")
    valid = set(refs) | set(keys)
    seen: set[str] = set()
    for s in mapping.segments:
        if s.segment_id in seen:
            errors.append(f"duplicate segment id '{s.segment_id}'")
        seen.add(s.segment_id)
        if (problem := bundle.check_ref(s.source)) is not None:
            errors.append(f"segment {s.segment_id}: {problem}")
        if s.item_ref is not None and s.item_ref not in valid:
            errors.append(f"segment {s.segment_id}: unknown item '{s.item_ref}'")
        if s.item_ref is None and s.association in {Association.PRIMARY, Association.RELATED}:
            errors.append(f"segment {s.segment_id}: {s.association} segment needs an item")
    return errors


def lint_draft(
    draft: DraftMinutes, mapping: EvidenceMap, selection: PolicySelection | None = None
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    paragraphs = {p.paragraph_id: p for item in draft.items for p in item.paragraphs}
    item_refs = {item.item_ref for item in draft.items}

    all_ids = [p.paragraph_id for item in draft.items for p in item.paragraphs]
    for dup in sorted({i for i in all_ids if all_ids.count(i) > 1}):
        issues.append(LintIssue("duplicate_paragraph", f"paragraph id '{dup}' is used twice"))

    expected = [i.ref for i in mapping.agenda_items]
    for ref in expected:
        if ref not in item_refs:
            issues.append(LintIssue("missing_item", f"agenda item {ref} has no minute"))

    for p in paragraphs.values():
        if match := PLACEHOLDER.search(p.text):
            issues.append(LintIssue("placeholder", f"{p.paragraph_id} contains '{match.group(0)}'"))

    for q in draft.questions:
        if q.anchor_kind == AnchorKind.PARAGRAPH:
            p = paragraphs.get(q.paragraph_id or "")
            if p is None:
                issues.append(
                    LintIssue("bad_anchor", f"{q.question_id} points at unknown paragraph")
                )
            elif not q.anchor_text or q.anchor_text not in p.text:
                issues.append(
                    LintIssue(
                        "bad_anchor", f"{q.question_id} anchor_text is not in {p.paragraph_id}"
                    )
                )
        elif q.anchor_kind == AnchorKind.ITEM_HEADING and q.item_ref not in item_refs:
            issues.append(LintIssue("bad_anchor", f"{q.question_id} points at unknown item"))

    if selection is not None:
        decided = {
            item.item_ref
            for item in selection.items
            if any(o.outcome_type in DECISIVE for o in item.outcomes)
        }
        for item in draft.items:
            for p in item.paragraphs:
                if p.outcome_type in DECISIVE and item.item_ref not in decided:
                    issues.append(
                        LintIssue(
                            "unsupported_outcome",
                            f"{p.paragraph_id} records '{p.outcome_type}' but the selection "
                            f"has no such outcome for item {item.item_ref}",
                        )
                    )
    return issues
