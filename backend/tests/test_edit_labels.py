"""DESS-051: each edit is labelled by kind, dimension and cause before anything is learned."""

from dataclasses import dataclass, field
from typing import Any

from app.minutes.alignment import word_diff
from app.minutes.edit_labels import (
    ROUTES,
    EditCause,
    Hunk,
    Route,
    attendee_names,
    code_label,
    group_findings,
    hunks,
    parse_date,
)
from app.minutes.profile_content import DateStyle, PresentationSettings
from tests import minutes_samples as samples

SETTINGS = PresentationSettings()
NAMES = attendee_names(samples.draft().header) | {"sarah mensah"}


@dataclass
class Row:
    """An alignment row, as far as the labelling needs one."""

    original_text: str
    final_text: str
    status: str = "changed"
    item_ref: str = "4"
    original_item_ref: str | None = "4"
    paragraph_id: str | None = "4.p1"
    role: str = "body"
    tracked: list[dict[str, Any]] = field(default_factory=list)
    comment_ids: list[str] = field(default_factory=list)
    id: str = "row"

    @property
    def diff(self) -> list[dict[str, str]]:
        return [s.model_dump() for s in word_diff(self.original_text, self.final_text)]


def label(before: str, after: str) -> tuple[str, list[str], str, str] | None:
    found = code_label(Hunk("E1", Row(before, after), 0, before, after), NAMES, SETTINGS)
    if found is None:
        return None
    return str(found.kind), [str(d) for d in found.dimensions], str(found.cause), found.pattern


def labelled(before: str, after: str) -> tuple[str, list[str], str, str]:
    found = label(before, after)
    assert found is not None, f"{before!r} -> {after!r} needs the model"
    return found


def test_changes_inside_a_paragraph_are_separate_edits() -> None:
    row = Row(
        "The Board approved the contract, capped at £1.2 million, and noted the risks.",
        "It was resolved that the contract be awarded, capped at £2.1 million, and noted the "
        "risks.",
    )
    found = [(h.before, h.after) for h in hunks([row])]
    assert found == [
        ("The Board approved", "It was resolved that"),
        ("", "be awarded"),
        ("£1.2", "£2.1"),
    ]


def test_whole_paragraph_edits() -> None:
    rows = [
        Row("", "Action: the Finance Director to sign.", status="added"),
        Row("Old paragraph.", "", status="removed"),
        Row("Same words.", "Same words.", status="moved", item_ref="3"),
        Row("Kept.", "Kept.", status="unchanged"),
    ]
    assert [(h.before, h.after) for h in hunks(rows)] == [
        ("", "Action: the Finance Director to sign."),
        ("Old paragraph.", ""),
        ("Same words.", "Same words."),
    ]


def test_formatting_only_is_found_from_tracked_formatting() -> None:
    row = Row("Kept.", "Kept.", status="unchanged", tracked=[{"kind": "format", "text": ""}])
    [h] = hunks([row])
    found = code_label(h, NAMES, SETTINGS)
    assert found is not None and found.pattern == "formatting only"


def test_cheap_cases_are_labelled_in_code() -> None:
    assert label("Ruth Okafor", "the Chair") == (
        "wording_style",
        ["WS4"],
        "profile_not_applied",
        "name replaced by role",
    )
    assert labelled("Sarah Mensah", "the Board")[2] == "profile_not_applied"
    assert label("the board", "the Board") == (
        "wording_style",
        ["WS6"],
        "profile_silent",
        "capitalisation of 'the board'",
    )
    assert labelled("approved,", "approved;")[3] == "punctuation or spacing"
    assert (
        labelled("12/03/2026", "12 March 2026")[2] == "profile_not_applied"
    )  # house style is LONG
    assert labelled("12 March 2026", "12th March 2026")[2] == "profile_silent"
    assert label("approved", "It was resolved that") is None  # needs the model
    assert label("£1.2 million", "£2.1 million") is None


def test_dates_in_common_forms() -> None:
    expected = parse_date("2026-03-12")
    assert expected is not None
    for text in ["12 March 2026", "12th March 2026", "March 12, 2026", "12/03/2026"]:
        assert parse_date(text) == expected
    assert parse_date("the budget") is None
    assert SETTINGS.date_style == DateStyle.LONG


def test_only_profile_silent_edits_become_candidates() -> None:
    assert ROUTES[EditCause.PROFILE_SILENT] == Route.CANDIDATE
    assert ROUTES[EditCause.PROFILE_NOT_APPLIED] == Route.DEFECT
    assert ROUTES[EditCause.EVIDENCE_MISREAD] == Route.DEFECT
    assert ROUTES[EditCause.MEETING_ONLY] == Route.MEETING_ONLY


@dataclass
class Label:
    before: str
    after: str
    source: str
    pattern: str
    cause: str = "profile_not_applied"
    kind: str = "wording_style"
    dimensions: list[str] = field(default_factory=lambda: ["WS4"])
    route: str = "defect"
    reason: str = "r"
    profile_basis: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    item: str = "4"
    id: str = "x"
    row: str = ""  # the paragraph; defaults to one per label

    @property
    def alignment(self) -> Row:
        return Row("", "", item_ref=self.item)

    @property
    def alignment_id(self) -> str:
        return self.row or f"{self.item}-{self.before}-{self.after}"


def test_repeated_edits_are_one_finding_with_a_count() -> None:
    labels = [Label(f"Director {n}", "the Board", "code", "name replaced by role", item=str(n))
              for n in range(1, 15)]  # fmt: skip
    labels += [
        Label("approved", "It was resolved that", "model", "resolution wording",
              cause="profile_silent", dimensions=["WS5"], route="candidate", item="2"),
        Label("approved", "It was resolved that", "model", "formal resolution phrasing",
              cause="profile_silent", dimensions=["WS5"], route="candidate", item="7"),
    ]  # fmt: skip

    findings = group_findings(labels)

    assert [(f.pattern, f.count, f.route) for f in findings] == [
        ("resolution wording", 2, "candidate"),
        ("name replaced by role", 14, "defect"),
    ]
    assert findings[0].items == ["2", "7"]


def test_similar_patterns_with_the_same_cause_are_one_finding() -> None:
    labels = [
        Label("Ruth Calder", "the Risk Committee Chair", "model", "name replaced with role title"),
        Label("Stephen Wren", "a director", "model", "director name replaced with role"),
        Label("Martin Vale", "the SID", "code", "name replaced by role"),
        Label("The Board approved", "It was resolved that", "model",
              "formal resolution phrasing introduced", cause="profile_silent",
              dimensions=["WS5"], route="candidate", row="8.p4"),
        Label("", "be approved", "model", "formal resolution wording adopted",
              cause="profile_silent", dimensions=["WS5"], route="candidate", row="8.p4"),
    ]  # fmt: skip

    findings = group_findings(labels)

    assert [(f.count, f.route) for f in findings] == [(1, "candidate"), (3, "defect")]


def test_roles_the_rules_recognise() -> None:
    for role in ["the Risk Committee Chair", "an independent non-executive director",
                 "the Chief Operating Officer", "the Board", "Directors"]:  # fmt: skip
        assert labelled("Ruth Calder", role)[3] == "name replaced by role", role
    assert label("Ruth Calder", "Ruth Calder-Smith") is None
