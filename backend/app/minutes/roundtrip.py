"""Item-level summary of an edited copy: how much of each agenda item the professional kept.

Built from the paragraph alignment (alignment.py). It gives the edit-effort score used for the
draft scores and the final item texts used as house examples.
"""

from difflib import SequenceMatcher
from enum import StrEnum

from pydantic import BaseModel

from app.minutes.alignment import Alignment, ParagraphStatus, similarity, words

__all__ = ["Comparison", "ItemChange", "WrongDraftError", "similarity", "summarise", "words"]

EDITED_AT = 0.6  # below this similarity an item counts as rewritten


class ChangeStatus(StrEnum):
    UNCHANGED = "unchanged"
    EDITED = "edited"
    REWRITTEN = "rewritten"
    DELETED = "deleted"
    ADDED = "added"


class ItemChange(BaseModel):
    item_ref: str
    heading: str
    status: ChangeStatus
    similarity: float
    words_added: int
    words_removed: int
    draft_text: str
    final_text: str


class ReviewerComment(BaseModel):
    author: str
    text: str


class Comparison(BaseModel):
    run_id: str | None  # the run id found in the file, if any
    items: list[ItemChange]
    comments: list[ReviewerComment]
    similarity: float  # word-weighted over all items, 0 to 1


class WrongDraftError(ValueError):
    pass


def summarise(
    alignment: Alignment, comments: list[ReviewerComment], run_id: str | None
) -> Comparison:
    rows = alignment.paragraphs
    changes = []
    for s in alignment.sections:
        # Everything but headings: an item's text includes any table in it, e.g. the actions.
        roles = {"title", "header", "body", "table", "action"}
        before = [
            r.original_text for r in rows if r.original_item_ref == s.item_ref and r.role in roles
        ]
        after = [
            r.final_text
            for r in rows
            if r.item_ref == s.item_ref and r.status != ParagraphStatus.REMOVED and r.role in roles
        ]
        changes.append(_change(s.item_ref, s.heading, "\n".join(before), "\n".join(after)))
    score = _weighted(changes)
    return Comparison(run_id=run_id, items=changes, comments=comments, similarity=score)


def _change(ref: str, heading: str, draft_text: str, final_text: str) -> ItemChange:
    a, b = words(draft_text), words(final_text)
    added = removed = 0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            removed += i2 - i1
            added += j2 - j1
    ratio = matcher.ratio() if a or b else 1.0
    if not a and b:
        status = ChangeStatus.ADDED
    elif a and not b:
        status, ratio = ChangeStatus.DELETED, 0.0
    elif a == b:
        status = ChangeStatus.UNCHANGED
    else:
        status = ChangeStatus.EDITED if ratio >= EDITED_AT else ChangeStatus.REWRITTEN
    return ItemChange(
        item_ref=ref,
        heading=heading,
        status=status,
        similarity=round(ratio, 4),
        words_added=added,
        words_removed=removed,
        draft_text=draft_text,
        final_text=final_text,
    )


def _weighted(changes: list[ItemChange]) -> float:
    """Similarity weighted by item size, so a rewritten long item counts for more."""
    weights = [max(len(words(c.draft_text)), len(words(c.final_text)), 1) for c in changes]
    total = sum(weights)
    return round(sum(c.similarity * w for c, w in zip(changes, weights, strict=True)) / total, 4)
