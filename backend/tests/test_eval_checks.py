from pathlib import Path

import pytest

from evals.checks import Assertion, check
from evals.minutes_eval import bundle_for, load_case
from tests import minutes_samples as samples

CASE = Path(__file__).parents[1] / "evals" / "cases" / "northbridge.yaml"


def run(**fields) -> tuple[bool, str]:
    return check(Assertion(**fields), samples.analysis(), samples.draft())


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"type": "outcome_present", "item": "4", "outcome": "approved"}, True),
        ({"type": "outcome_present", "item": "3", "outcome": "approved"}, False),
        ({"type": "outcome_absent", "item": "3", "outcome": "approved"}, True),
        ({"type": "question_exists", "item": "4", "pattern": "(?i)tenants"}, True),
        ({"type": "question_exists", "item": "2", "pattern": "."}, False),
        ({"type": "no_questions", "item": "3"}, True),
        ({"type": "body_matches", "item": "4", "pattern": "1\\.2"}, True),
        ({"type": "body_not_matches", "pattern": "(?i)car park"}, True),
        ({"type": "body_not_matches", "item": "4", "pattern": "(?i)contingency"}, False),
        ({"type": "segment_maps", "source": "T", "lines": [7, 12], "item": "4"}, True),
        ({"type": "segment_maps", "source": "T", "lines": [7, 12], "item": "3"}, False),
        ({"type": "no_placeholders"}, True),
    ],
)
def test_assertions(fields: dict, expected: bool) -> None:
    ok, _ = run(**fields)
    assert ok is expected


def test_example_case_loads_and_paths_resolve() -> None:
    case = load_case(CASE)
    assert case.name == "northbridge"
    bundle = bundle_for(case)
    assert [s.source_id for s in bundle.sources] == ["A", "T"]
    assert all(check_type in {a.type for a in case.assertions}
               for check_type in ("outcome_present", "question_exists"))  # fmt: skip
