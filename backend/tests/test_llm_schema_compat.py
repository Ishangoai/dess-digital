"""Stage output schemas must stay simple enough for Gemini structured output."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.minutes.llm_schemas import (
    DraftMinutes,
    EvidenceAnalysis,
    PolicySelection,
    Reconsideration,
    ValidationReport,
)

STAGE_SCHEMAS = [EvidenceAnalysis, PolicySelection, DraftMinutes, ValidationReport, Reconsideration]


def walk(node: Any, path: str = "#"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}/{i}")


def depth(name: str, defs: dict[str, Any], seen: tuple[str, ...] = ()) -> int:
    if name in seen:
        raise AssertionError(f"recursive schema via {' -> '.join((*seen, name))}")
    refs = {
        node["$ref"].rsplit("/", 1)[-1]
        for _, node in walk(defs[name])
        if isinstance(node.get("$ref"), str)
    }
    return 1 + max((depth(r, defs, (*seen, name)) for r in refs), default=0)


@pytest.mark.parametrize("model", STAGE_SCHEMAS, ids=lambda m: m.__name__)
def test_schema_is_gemini_friendly(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()
    defs = {**schema.get("$defs", {}), model.__name__: schema}

    for path, node in walk(schema):
        assert "oneOf" not in node and "discriminator" not in node, path
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is not True, path
            missing = set(node["properties"]) - set(node.get("required", []))
            assert not missing, f"{path}: optional fields {missing} must be required + nullable"
        assert "additionalProperties" not in node or node["additionalProperties"] is False, path

    assert depth(model.__name__, defs) <= 6
