from app.minutes.evidence import EvidenceBundle, SourceRole, SourceText, source_ids_for
from app.minutes.llm_schemas import LineRef


def bundle() -> EvidenceBundle:
    return EvidenceBundle(
        [
            SourceText("A", SourceRole.AGENDA, "agenda.txt", "1. Apologies\n2. Roof"),
            SourceText("T", SourceRole.TRANSCRIPT, "t.txt", "one\n\ntwo\nthree\nfour\n\nfive"),
        ]
    )


def test_source_ids() -> None:
    roles = [SourceRole.AGENDA, SourceRole.TRANSCRIPT, SourceRole.NOTES, SourceRole.PAPER]
    assert source_ids_for([*roles, SourceRole.PAPER]) == ["A", "T", "N", "P1", "P2"]


def test_numbering_skips_blank_lines_but_keeps_numbers() -> None:
    transcript = bundle().get("T")
    assert transcript is not None
    assert transcript.numbered().split("\n") == [
        "T1| one",
        "T3| two",
        "T4| three",
        "T5| four",
        "T7| five",
    ]


def test_render_wraps_sources_in_tags() -> None:
    text = bundle().render()
    assert '<agenda source_id="A" filename="agenda.txt">' in text
    assert "A2| 2. Roof" in text
    assert text.endswith("</transcript>")


def test_check_ref() -> None:
    b = bundle()
    assert b.check_ref(LineRef(source_id="T", start=1, end=7)) is None
    assert "outside" in (b.check_ref(LineRef(source_id="T", start=5, end=9)) or "")
    assert "unknown source" in (b.check_ref(LineRef(source_id="X", start=1, end=1)) or "")


def test_excerpt() -> None:
    assert bundle().excerpt(LineRef(source_id="T", start=3, end=4)) == "two\nthree"


def test_uncovered_ranges_merge_across_blank_lines() -> None:
    covered = [LineRef(source_id="T", start=4, end=4)]
    gaps = bundle().uncovered(covered)
    assert [(g.start, g.end) for g in gaps] == [(1, 3), (5, 7)]
