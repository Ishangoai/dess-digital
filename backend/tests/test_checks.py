from pathlib import Path

from app.minutes.checks import lint_draft, validate_mapping
from app.minutes.evidence import EvidenceBundle, SourceRole, SourceText
from app.minutes.llm_schemas import AnchorKind, EvidenceMap, OutcomeType
from tests import minutes_samples as samples

FIXTURES = Path(__file__).parent / "fixtures" / "minutes"


def bundle() -> EvidenceBundle:
    return EvidenceBundle(
        [
            SourceText("A", SourceRole.AGENDA, "agenda.txt", (FIXTURES / "agenda.txt").read_text()),
            SourceText(
                "T", SourceRole.TRANSCRIPT, "t.txt", (FIXTURES / "transcript.txt").read_text()
            ),
        ]
    )


def mapping() -> EvidenceMap:
    return samples.analysis().evidence_map()


def codes(issues) -> list[str]:
    return [i.code for i in issues]


def test_sample_mapping_is_valid() -> None:
    assert validate_mapping(mapping(), bundle()) == []


def test_mapping_errors() -> None:
    m = mapping()
    m.segments[0].source.end = 999
    m.segments[1].item_ref = "9"
    m.segments[2].segment_id = m.segments[3].segment_id
    errors = validate_mapping(m, bundle())
    assert any("outside" in e for e in errors)
    assert any("unknown item '9'" in e for e in errors)
    assert any("duplicate segment id" in e for e in errors)


def test_clean_draft_has_no_issues() -> None:
    assert lint_draft(samples.draft(), mapping(), samples.selection()) == []


def test_missing_item_and_placeholder() -> None:
    draft = samples.draft()
    draft.items = draft.items[:-1]
    draft.items[0].paragraphs[0].text = "Apologies were received from [name]."
    assert codes(lint_draft(draft, mapping())) == ["missing_item", "placeholder"]


def test_bad_anchor() -> None:
    draft = samples.draft()
    draft.questions[0].anchor_text = "not in the paragraph"
    assert codes(lint_draft(draft, mapping())) == ["bad_anchor"]

    draft.questions[0].anchor_kind = AnchorKind.ITEM_HEADING
    draft.questions[0].item_ref = "99"
    assert codes(lint_draft(draft, mapping())) == ["bad_anchor"]


def test_approval_without_selected_approval_is_flagged() -> None:
    draft = samples.draft()
    draft.items[2].paragraphs[0].outcome_type = OutcomeType.APPROVED  # item 3 was only noted
    assert codes(lint_draft(draft, mapping(), samples.selection())) == ["unsupported_outcome"]
