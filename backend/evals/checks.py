"""Judgement checks run against a pipeline result."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.minutes.checks import PLACEHOLDER
from app.minutes.llm_schemas import DraftMinutes, EvidenceAnalysis, OutcomeType


class Assertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "outcome_present",
        "outcome_absent",
        "question_exists",
        "no_questions",
        "body_matches",
        "body_not_matches",
        "segment_maps",
        "no_placeholders",
    ]
    item: str | None = None
    outcome: OutcomeType | None = None
    pattern: str | None = None
    source: str | None = None
    lines: tuple[int, int] | None = None
    note: str | None = None  # why this check matters


def check(a: Assertion, analysis: EvidenceAnalysis, draft: DraftMinutes) -> tuple[bool, str]:
    """(passed, detail) for one assertion."""
    items = {i.item_ref: i for i in draft.items}

    def item_text(ref: str | None) -> str:
        chosen = [items[ref]] if ref in items else ([] if ref else list(items.values()))
        return "\n".join(p.text for i in chosen for p in i.paragraphs)

    def outcomes(ref: str | None) -> set[Any]:
        item = items.get(ref or "")
        return {p.outcome_type for p in item.paragraphs} if item else set()

    match a.type:
        case "outcome_present":
            found = outcomes(a.item)
            return a.outcome in found, f"item {a.item} outcomes: {sorted(map(str, found - {None}))}"
        case "outcome_absent":
            found = outcomes(a.item)
            return (
                a.outcome not in found,
                f"item {a.item} outcomes: {sorted(map(str, found - {None}))}",
            )
        case "question_exists":
            qs = [q.question for q in draft.questions if a.item is None or q.item_ref == a.item]
            hit = any(re.search(a.pattern or ".", q) for q in qs)
            return hit, f"{len(qs)} question(s) for item {a.item}: {qs}"
        case "no_questions":
            qs = [q.question for q in draft.questions if a.item is None or q.item_ref == a.item]
            return not qs, f"questions: {qs}"
        case "body_matches":
            return bool(re.search(a.pattern or "", item_text(a.item))), f"pattern {a.pattern!r}"
        case "body_not_matches":
            m = re.search(a.pattern or "", item_text(a.item))
            return m is None, f"found {m.group(0)!r}" if m else "not found"
        case "segment_maps":
            start, end = a.lines or (0, 0)
            covering = [
                s.item_ref
                for s in analysis.segments
                if s.source.source_id == a.source
                and s.source.start <= start
                and s.source.end >= end
            ]
            return a.item in covering, f"lines {a.source}{start}-{end} mapped to {covering}"
        case "no_placeholders":
            m = PLACEHOLDER.search(item_text(None))
            return m is None, f"found {m.group(0)!r}" if m else "none"
