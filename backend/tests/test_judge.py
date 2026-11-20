from pathlib import Path

import pytest

from app.llm import LLMClient
from app.llm.types import Completion, CompletionRequest
from app.minutes.evidence import EvidenceBundle, SourceRole, SourceText
from evals.judge import (
    ItemScore,
    Judge,
    Minutes,
    PairVerdict,
    ScoreReport,
    Winner,
    averages,
    load_minutes,
)
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider


def judge(provider: ScriptedProvider) -> Judge:
    bundle = EvidenceBundle([SourceText("A", SourceRole.AGENDA, "a.txt", "1. Roof contract")])
    return Judge(LLMClient(provider, "judge-model"), "THE LOGIC", bundle, max_tokens=1000)


def score(ref: str, value: int) -> ItemScore:
    return ItemScore(item_ref=ref, heading="h", covered=True, outcome=value, substance=value,
                     challenge=value, actions=value, accuracy=value, style=value, missing=[],
                     errors=[])  # fmt: skip


def test_score_sends_logic_evidence_and_minutes() -> None:
    provider = ScriptedProvider({"ScoreReport": ScoreReport(items=[score("1", 4)], summary="ok")})

    report = judge(provider).score(Minutes("m", "The Board approved the contract."))

    request = provider.requests[0]
    assert request.system is not None and request.system.endswith("THE LOGIC")
    assert "A1| 1. Roof contract" in request.messages[0].content
    assert "<minutes>\nThe Board approved the contract." in request.messages[0].content
    assert averages(report)["overall"] == 4


def test_averages_over_items() -> None:
    report = ScoreReport(items=[score("1", 5), score("2", 3)], summary="")
    assert averages(report)["outcome"] == 4
    assert averages(report)["overall"] == 4


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (Winner.FIRST, Winner.SECOND, Winner.FIRST),  # a wins in both orders
        (Winner.SECOND, Winner.FIRST, Winner.SECOND),  # b wins in both orders
        (Winner.FIRST, Winner.FIRST, Winner.TIE),  # always prefers the first shown: bias
    ],
)
def test_compare_runs_both_orders(first: Winner, second: Winner, expected: Winner) -> None:
    verdicts = iter([first, second])

    class Alternating(ScriptedProvider):
        def complete(self, request: CompletionRequest) -> Completion:
            self.responses["PairVerdict"] = PairVerdict(reasons=[], winner=next(verdicts))
            return super().complete(request)

    provider = Alternating({})
    assert judge(provider).compare(Minutes("a", "A"), Minutes("b", "B")) == expected
    first_message = provider.requests[0].messages[0].content
    assert first_message.index("\nA\n") < first_message.index("\nB\n")


def test_load_draft_json_uses_the_folder_name(tmp_path: Path) -> None:
    path = tmp_path / "C-run" / "draft.json"
    path.parent.mkdir()
    path.write_text(samples.draft().model_dump_json(), encoding="utf-8")

    minutes = load_minutes(path)

    assert minutes.label == "C-run"
    assert "## 4 Roof replacement programme" in minutes.text
    assert "4.p2" not in minutes.text  # ids are not part of the record
    assert minutes.words > 50
