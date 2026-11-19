"""Explaining and sorting the professional's edits. Invented text only; the model is faked."""

import pytest

from app.minutes.docx_compare import (
    CommentReply,
    CommentThread,
    Comparison,
    ParagraphChange,
    Status,
)
from app.minutes.edit_review import (
    ROUTES,
    ClassifiedChange,
    EditCause,
    EditClassification,
    EditKind,
    EditReview,
    Route,
    Support,
    accept_review,
    attendee_names,
    build_result,
    classify_by_rule,
    date_format_change,
    group_patterns,
    name_replaced_by_role,
    plan_review,
    render_lines,
)
from app.minutes.evidence import EvidenceBundle, SourceRole, SourceText
from app.minutes.llm_schemas import EvidenceMap
from app.minutes.profile_content import DimensionCode, ProfileContent
from tests import minutes_samples as samples

PEOPLE = ["Ruth Okafor", "Amaka Bello", "Sam Hale", "Priya Shah", "Tom Reid"]
TRANSCRIPT = "\n".join(f"line {n} of the invented transcript" for n in range(1, 21))
SPEAKERS = "Chair (Ruth Okafor): Welcome.\nPriya Shah: A question.\nSeveral voices: Agreed."


def change(
    original: str | None,
    edited: str | None,
    status: Status = "changed",
    section: str = "4",
    pid: str | None = "4.p1",
    change_id: str = "C1",
    **extra,
) -> ParagraphChange:
    return ParagraphChange(
        change_id=change_id,
        status=status,
        section=section,
        paragraph_id=pid,
        heading=False,
        original=original,
        edited=edited,
        original_index=0 if original is not None else None,
        edited_index=0 if edited is not None else None,
        matched_by="bookmark",
        similarity=None,
        text_changed=original != edited,
        format_only=False,
        diff=[],
        tracked_changes=[],
        comment_ids=extra.pop("comment_ids", []),
        **extra,
    )


def bundle() -> EvidenceBundle:
    return EvidenceBundle(
        [
            SourceText("A", SourceRole.AGENDA, "agenda.txt", "1 Apologies\n4 Roof"),
            SourceText("T", SourceRole.TRANSCRIPT, "transcript.txt", TRANSCRIPT),
            SourceText("N", SourceRole.NOTES, "notes.txt", SPEAKERS),
        ]
    )


# code rules


def test_formatting_only_is_recorded_without_a_model(profile_content: ProfileContent) -> None:
    c = change("Same words.", "Same  words.", status="unchanged")
    c.format_only = True
    settled = classify_by_rule(c, profile_content, PEOPLE)
    assert settled is not None
    assert (settled.rule, settled.dimension, settled.route) == (
        "formatting_only",
        DimensionCode.WS6,
        Route.MEETING_ONLY,
    )


@pytest.mark.parametrize(
    ("original", "edited", "expected"),
    [
        (
            "The next meeting is on 12/03/2026.",
            "The next meeting is on 12 March 2026.",
            ("numeric", "long"),
        ),
        ("Due 12 March 2026.", "Due 12th March 2026.", ("long", "ordinal")),
        ("Due March 12, 2026.", "Due 12 March 2026.", ("month_first", "long")),
        ("Due 12 March 2026.", "Due 13 March 2026.", None),  # a different date
        ("Due 12 March 2026.", "Due 12 March 2026, if funded.", None),  # more than the date
    ],
)
def test_date_format_change(original: str, edited: str, expected: tuple[str, str] | None) -> None:
    assert date_format_change(original, edited) == expected


def test_date_rule_checks_the_profile_date_style(profile_content: ProfileContent) -> None:
    to_long = classify_by_rule(change("On 12/03/2026.", "On 12 March 2026."), profile_content, [])
    assert to_long is not None and to_long.cause == EditCause.PROFILE_NOT_APPLIED  # profile: long

    to_ordinal = classify_by_rule(
        change("On 12 March 2026.", "On 12th March 2026."), profile_content, []
    )
    assert to_ordinal is not None and to_ordinal.cause == EditCause.PROFILE_SILENT_OR_DIFFERENT
    assert to_ordinal.route == Route.CANDIDATE_RULE


@pytest.mark.parametrize(
    ("original", "edited", "expected"),
    [
        ("Priya Shah remained concerned.", "One trustee remained concerned.", True),
        ("Ms Shah asked about cost.", "The Board asked about cost.", True),
        ("Tom Reid's report was noted.", "The Chief Executive's report was noted.", True),
        ("Priya Shah asked about cost.", "Tom Reid asked about cost.", False),  # name for name
        ("Priya Shah asked about cost.", "The Board asked about cost and timing.", False),
        ("The Board asked about cost.", "The Board asked about cost.", False),
    ],
)  # fmt: skip
def test_name_replaced_by_role(original: str, edited: str, expected: bool) -> None:
    assert name_replaced_by_role(original, edited, PEOPLE) is expected


def test_name_rule_uses_ws4(profile_content: ProfileContent) -> None:
    c = change("Priya Shah asked about cost.", "The Board asked about cost.")
    settled = classify_by_rule(c, profile_content, PEOPLE)
    assert settled is not None
    assert (settled.dimension, settled.cause) == (DimensionCode.WS4, EditCause.PROFILE_NOT_APPLIED)
    assert settled.profile_text == "Attribute collectively by default."

    silent = profile_content.model_copy(deep=True)
    ws4 = next(d for d in silent.writing_style if d.code == DimensionCode.WS4)
    ws4.default_standard, ws4.provisions = "Name speakers where it helps.", []
    settled = classify_by_rule(c, silent, PEOPLE)
    assert settled is not None and settled.cause == EditCause.PROFILE_SILENT_OR_DIFFERENT


def test_other_edits_go_to_the_model(profile_content: ProfileContent) -> None:
    c = change("The Board approved £1.2 million.", "The Board approved £1.3 million.")
    assert classify_by_rule(c, profile_content, PEOPLE) is None


# what the model is given


def comparison(
    *changes: ParagraphChange, comments: list[CommentThread] | None = None
) -> Comparison:
    sections = {}
    for c in changes:
        sections.setdefault(c.section, []).append(c)
    return Comparison.model_validate(
        {
            "counts": {},
            "sections": [
                {
                    "section": k,
                    "heading": f"{k} Item",
                    "counts": {},
                    "changes": [x.model_dump() for x in v],
                }
                for k, v in sections.items()
            ],
            "comments": [t.model_dump() for t in comments or []],
            "tracked_change_authors": [],
            "bookmarks_expected": 0,
            "bookmarks_found": 0,
        }
    )


def test_plan_sends_one_request_per_item(profile_content: ProfileContent) -> None:
    draft = samples.draft()
    draft.items[3].paragraphs[1].based_on = ["O1"]
    thread = CommentThread(
        comment_id="0", author="DESS Minutes", date=None, text="Who writes?", question_id="Q1",
        resolved=False, section="4", paragraph_id="4.p2", edited_index=3,
        replies=[CommentReply(comment_id="1", author="Company Secretary", date=None,
                              text="Sam Hale.")],
    )  # fmt: skip
    roof = change(
        "The Board approved phase one only, capped at £1.2 million.",
        "The Board approved phase one, capped at £1.3 million.",
        pid="4.p2",
        change_id="C2",
        comment_ids=["0"],
    )
    plan = plan_review(
        comparison(
            change("Priya Shah asked about cost.", "The Board asked about cost.", change_id="C1"),
            roof,
            change(None, "A new line.", status="added", section="3", pid=None, change_id="C3"),
            comments=[thread],
        ),
        draft,
        profile_content,
        samples.selection(),
        EvidenceMap.model_validate(samples.analysis().evidence_map().model_dump()),
        bundle(),
    )

    assert [c.change_id for c in plan.by_rule] == ["C1"]
    assert [(r.section, [c.change_id for c in r.changes]) for r in plan.requests] == [
        ("4", ["C2"]),
        ("3", ["C3"]),
    ]
    message = plan.requests[0].message
    assert "C2 (changed; paragraph 4.p2; outcome paragraph; based on O1)" in message
    assert "Capped at £1.2 million" in message  # the selection entry
    assert "T11 line 11 of the invented transcript" in message  # its cited lines
    assert "Reply by Company Secretary: Sam Hale." in message
    assert "WS4 Attribution" in plan.system  # the profile


def test_render_lines_merges_and_caps() -> None:
    text = render_lines(bundle(), [samples.ref(2, 3), samples.ref(3, 4), samples.ref(9, 9)])
    assert text.splitlines() == [
        "T2 line 2 of the invented transcript",
        "T3 line 3 of the invented transcript",
        "T4 line 4 of the invented transcript",
        "...",
        "T9 line 9 of the invented transcript",
    ]
    assert render_lines(bundle(), [samples.ref(1, 20)], limit=2).endswith("(more lines omitted)")


# accepting the answer, grouping and routing


def classification(change_id: str, **overrides) -> EditClassification:
    values = {
        "change_id": change_id,
        "kind": EditKind.WORDING_OR_STYLE,
        "dimension": DimensionCode.WS5,
        "cause": EditCause.PROFILE_SILENT_OR_DIFFERENT,
        "support": Support.NOT_APPLICABLE,
        "support_refs": [],
        "profile_text": None,
        "reason": "Invented reason.",
    } | overrides
    return EditClassification.model_validate(values)


def test_accept_review_keeps_only_what_was_asked(profile_content: ProfileContent) -> None:
    plan = plan_review(
        comparison(
            change("a b c", "a b d", change_id="C1"),
            change(None, "New fact.", status="added", pid=None, change_id="C2"),
        ),
        samples.draft(),
        profile_content,
        None,
        None,
        bundle(),
    )
    [request] = plan.requests
    review = EditReview(
        classifications=[
            classification("C1", profile_text="ignored for this cause"),
            classification("C1", kind=EditKind.STRUCTURE),  # duplicate, ignored
            classification(
                "C2",
                kind=EditKind.CONTENT_ADDED,
                cause=EditCause.MEETING_SPECIFIC,
                support=Support.TRANSCRIPT,
                support_refs=[samples.ref(5, 6), samples.ref(90, 95)],  # second is not real
            ),
            classification("C9"),  # not asked about
        ]
    )
    accepted = {c.change_id: c for c in accept_review(review, request, profile_content, bundle())}

    assert set(accepted) == {"C1", "C2"}
    assert accepted["C1"].kind == EditKind.WORDING_OR_STYLE and accepted["C1"].profile_text is None
    assert accepted["C1"].dimension_title == "Decisions"
    assert accepted["C2"].support == Support.TRANSCRIPT
    assert [(r.start, r.end) for r in accepted["C2"].support_refs] == [(5, 6)]

    result = build_result(list(accepted.values())[:1], request.changes)
    assert result.unclassified == ["C2"]


def classified(change_id: str, section: str, cause: EditCause, kind=EditKind.WORDING_OR_STYLE,
               dimension=DimensionCode.WS5) -> ClassifiedChange:  # fmt: skip
    return ClassifiedChange(
        change_id=change_id, section=section, paragraph_id=f"{section}.p1", kind=kind,
        dimension=dimension, dimension_title="Decisions", cause=cause, route=ROUTES[cause],
        support=Support.NOT_APPLICABLE, support_refs=[], profile_text=None,
        reason=f"Reason {change_id}.", decided_by="model",
    )  # fmt: skip


def test_repeats_become_one_pattern_and_route_by_cause() -> None:
    patterns = group_patterns(
        [
            classified("C1", "2", EditCause.PROFILE_SILENT_OR_DIFFERENT),
            classified("C4", "4", EditCause.PROFILE_SILENT_OR_DIFFERENT),
            classified("C5", "4", EditCause.PROFILE_NOT_APPLIED),
            classified("C6", "5", EditCause.EVIDENCE_MISREAD, kind=EditKind.FACTUAL_CORRECTION,
                       dimension=DimensionCode.MP4),
            classified("C7", "5", EditCause.MEETING_SPECIFIC),
        ]
    )  # fmt: skip

    summary = [(p.pattern_id, p.cause, p.route, p.count, p.paragraph_ids) for p in patterns]
    assert summary == [
        ("E1", EditCause.PROFILE_SILENT_OR_DIFFERENT, Route.CANDIDATE_RULE, 2, ["2.p1", "4.p1"]),
        ("E2", EditCause.PROFILE_NOT_APPLIED, Route.DRAFT_MISTAKE, 1, ["4.p1"]),
        ("E3", EditCause.EVIDENCE_MISREAD, Route.DRAFT_MISTAKE, 1, ["5.p1"]),
        ("E4", EditCause.MEETING_SPECIFIC, Route.MEETING_ONLY, 1, ["5.p1"]),
    ]
    assert patterns[0].reasons == ["Reason C1.", "Reason C4."]


def test_people_include_speaker_labels() -> None:
    names = attendee_names(samples.draft(), samples.selection(), bundle())
    assert {"Priya Shah", "Ruth Okafor", "Sam Hale"} <= set(names)
    assert not {"Chair", "Several voices", "Several"} & set(names)
