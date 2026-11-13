from dev_ui import render
from tests import minutes_samples as samples


def review() -> dict:
    mapping = samples.analysis().evidence_map().model_dump(mode="json")
    segments = [s | {"excerpt": "..."} for s in mapping["segments"]]
    return {"mapping": mapping, "segments": segments, "uncovered": [], "uncovered_excerpts": []}


def test_mapping_table_round_trip() -> None:
    r = review()
    rows = render.mapping_rows(r)
    assert rows[3][:5] == ["S4", "T", 6, 13, "4"]

    rows[3][2] = "5"  # edited in the table, Gradio may hand back strings
    rows[0][4] = ""
    rows.append(["", "", "", "", "", "", ""])  # blank row is ignored
    mapping = render.mapping_from_rows(r["mapping"], rows)

    assert mapping["agenda_items"] == r["mapping"]["agenda_items"]
    assert mapping["segments"][3]["source"] == {"source_id": "T", "start": 5, "end": 13}
    assert mapping["segments"][0]["item_ref"] is None
    assert len(mapping["segments"]) == 5


def test_draft_markdown_highlights_anchor_and_shows_question() -> None:
    md = render.draft_markdown(samples.draft().model_dump(mode="json"))
    assert "## 4 Roof replacement programme: contract award" in md
    assert "The Board approved ==phase one only==, capped at £1.2 million." in md
    assert "> **Q1** Who was asked to write to tenants about the roof works?" in md


def test_review_notes_pair_findings_with_decisions() -> None:
    run = {
        "validation": samples.validation().model_dump(mode="json"),
        "reconsideration": samples.reconsideration().model_dump(mode="json"),
        "lint": ["[placeholder] 1.p1 contains '[name]'"],
        "draft": None,
    }
    notes = render.review_notes(run)
    assert "Authority to sign the contract is missing. -> **accept**: Agreed." in notes
    assert "[placeholder]" in notes


def test_usage_rows_include_total() -> None:
    run = {
        "llm_calls": [
            {"stage": "evidence", "model": "m", "input_tokens": 10, "output_tokens": 2,
             "latency_ms": 1500, "ok": True, "error": None},
        ],
        "usage_total": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
                        "latency_ms": 1500},
    }  # fmt: skip
    assert render.usage_rows(run) == [
        ["evidence", "m", 10, 2, 1.5, "ok"],
        ["total", "", 10, 2, 1.5, ""],
    ]
