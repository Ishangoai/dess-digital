"""Proposed profile changes learned from edits. Invented text only; the model is never called."""

import dataclasses
from typing import Any

import pytest

from app.minutes.amendments import (
    Accepted,
    AmendmentDraft,
    AmendmentError,
    Operation,
    Overlap,
    apply,
    check,
    dimension_of,
    message,
)
from app.minutes.edit_review import EditCause, EditKind, EditPattern, Route
from app.minutes.profile_content import DimensionCode, ProfileContent, Provenance, ProvisionKind
from app.services.profile import check_floors
from tests.test_edit_review import change

RULE = "Lead each decision with the body and the verb."


def pattern(dimension: DimensionCode = DimensionCode.WS5, *ids: str) -> EditPattern:
    ids = ids or ("C1",)
    return EditPattern(
        pattern_id="E1",
        kind=EditKind.WORDING_OR_STYLE,
        dimension=dimension,
        dimension_title="ignored",
        cause=EditCause.PROFILE_SILENT_OR_DIFFERENT,
        route=Route.CANDIDATE_RULE,
        count=len(ids),
        change_ids=list(ids),
        paragraph_ids=list(ids),
        reasons=["Invented reason."],
    )


def draft(**values: object) -> AmendmentDraft:
    base = {
        "operation": "add",
        "target_rule_id": None,
        "text": RULE,
        "kind": "preference",
        "overlap": "none",
        "overlap_with": None,
        "reason": "Invented reason.",
    }
    return AmendmentDraft.model_validate({**base, **values})


def accepted(**values: Any) -> Accepted:
    rule = Accepted(
        dimension=DimensionCode.WS5,
        operation=Operation.ADD,
        target_rule_id=None,
        text=RULE,
        kind=ProvisionKind.PREFERENCE,
        refused=None,
    )
    return dataclasses.replace(rule, **values)


def test_message_gives_the_rules_floors_and_edits(profile_content: ProfileContent) -> None:
    c = change("The plan was approved.", "The Board approved the plan.")
    text = message(pattern(DimensionCode.WS4), {"C1": c}, {"C1": "Active voice."}, profile_content)

    assert "ws4-names-for-actions [preference]:" in text
    assert "F1 " in text and "<hard_floors>" in text
    assert "Draft: The plan was approved.\nEdited: The Board approved the plan." in text
    assert "Why: Active voice." in text


def test_fixed_rules_are_marked(profile_content: ProfileContent) -> None:
    text = message(pattern(DimensionCode.MP4), {}, {}, profile_content)
    assert "mp4-no-silent-approval [evidential_fundamental, fixed]:" in text


def test_an_added_rule_is_allowed(profile_content: ProfileContent) -> None:
    a = check(draft(), pattern(), profile_content)
    assert (a.operation, a.text, a.refused) == (Operation.ADD, RULE, None)
    assert a.target_rule_id is None and a.change_ids == ["C1"]


@pytest.mark.parametrize(
    ("dimension", "values", "why"),
    [
        (DimensionCode.MP4, {"operation": "replace", "target_rule_id": "mp4-no-silent-approval"},
         "fixed rule"),
        (DimensionCode.MP4, {"operation": "remove", "target_rule_id": "mp4-no-silent-approval",
                             "text": None}, "fixed rule"),
        (DimensionCode.WS5, {"operation": "replace", "target_rule_id": "F2"}, "Hard floors"),
        (DimensionCode.WS5, {"overlap": "conflict", "overlap_with": "F1"}, "hard floor"),
        (DimensionCode.WS5, {"operation": "replace", "target_rule_id": "ws5-nothing"}, "no such"),
        (DimensionCode.WS5, {"text": "  "}, "No wording"),
    ],
)  # fmt: skip
def test_code_refuses_what_may_not_change(
    profile_content: ProfileContent, dimension: DimensionCode, values: dict, why: str
) -> None:
    a = check(draft(**values), pattern(dimension), profile_content)
    assert a.refused is not None and why in a.refused


def test_duplicates_and_conflicts_are_flagged(profile_content: ProfileContent) -> None:
    dup = check(draft(overlap="duplicate", overlap_with="standard"), pattern(), profile_content)
    assert (dup.overlap, dup.overlap_with, dup.refused) == (Overlap.DUPLICATE, "standard", None)

    conflict = check(
        draft(operation="replace", target_rule_id="ws4-names-for-actions", overlap="conflict",
              overlap_with="ws4-names-for-actions"),
        pattern(DimensionCode.WS4),
        profile_content,
    )  # fmt: skip
    assert conflict.refused is None
    assert (conflict.overlap, conflict.overlap_with) == (Overlap.CONFLICT, "ws4-names-for-actions")

    unknown = check(draft(overlap="duplicate", overlap_with="made-up"), pattern(), profile_content)
    assert unknown.overlap_with is None


def test_apply_adds_a_learned_rule_and_leaves_the_parent(profile_content: ProfileContent) -> None:
    before = profile_content.model_dump()
    content, summary = apply(profile_content, [accepted(), accepted(text="Another.")], "Note.")

    [first, second] = dimension_of(content, DimensionCode.WS5).provisions
    assert (first.id, second.id) == ("ws5-learned-1", "ws5-learned-2")
    assert (first.text, first.kind, first.provenance) == (
        RULE,
        ProvisionKind.PREFERENCE,
        Provenance.PROFESSIONAL_PREFERENCE,
    )
    assert first.source_note == "Note."
    assert summary.startswith("Note.\nWS5: added a rule.")
    assert check_floors(profile_content, content) == []
    assert profile_content.model_dump() == before


def test_apply_rewords_or_removes_a_preference(profile_content: ProfileContent) -> None:
    reworded, _ = apply(
        profile_content,
        [accepted(dimension=DimensionCode.WS4, operation=Operation.REPLACE,
                  target_rule_id="ws4-names-for-actions", text="Name action owners by role.")],
        "Note.",
    )  # fmt: skip
    [rule] = dimension_of(reworded, DimensionCode.WS4).provisions
    assert (rule.id, rule.text) == ("ws4-names-for-actions", "Name action owners by role.")

    removed, summary = apply(
        profile_content,
        [accepted(dimension=DimensionCode.WS4, operation=Operation.REMOVE,
                  target_rule_id="ws4-names-for-actions", text=None)],
        "Note.",
    )  # fmt: skip
    assert dimension_of(removed, DimensionCode.WS4).provisions == []
    assert "removed ws4-names-for-actions" in summary


@pytest.mark.parametrize(
    "values",
    [
        {"refused": "This is a fixed rule that cannot be changed."},
        {"dimension": DimensionCode.MP4, "operation": Operation.REPLACE,
         "target_rule_id": "mp4-no-silent-approval"},
        {"dimension": DimensionCode.MP4, "operation": Operation.REMOVE,
         "target_rule_id": "mp4-no-silent-approval"},
    ],
)  # fmt: skip
def test_apply_never_changes_a_fixed_rule(profile_content: ProfileContent, values: dict) -> None:
    with pytest.raises(AmendmentError):
        apply(profile_content, [accepted(**values)], "Note.")
