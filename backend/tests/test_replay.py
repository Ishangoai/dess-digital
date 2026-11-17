from evals.replay import closeness
from tests import minutes_samples as samples


def final(ref: str, text: str) -> dict:
    return {"item_ref": ref, "final_text": text}


def test_identical_items_are_fully_close() -> None:
    draft = samples.draft()
    finals = [final(i.item_ref, "\n".join(p.text for p in i.paragraphs)) for i in draft.items]
    assert closeness(draft, [final("header", "ignored"), *finals]) == 1.0


def test_missing_and_changed_items_lower_closeness() -> None:
    draft = samples.draft()
    finals = [
        final("3", "The Board noted the report."),
        final("9", "An item the draft does not have at all."),
    ]
    score = closeness(draft, finals)
    assert 0.2 < score < 0.6
