from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm import LLMClient, LLMProviderError, get_llm_client
from app.main import app as main_app
from app.routers import llm as llm_routes
from tests.test_llm_client import FakeProvider


def client_with(provider: FakeProvider) -> TestClient:
    app = FastAPI()
    app.include_router(llm_routes.router, prefix="/api")
    app.dependency_overrides[get_llm_client] = lambda: LLMClient(provider, "fake-model")
    return TestClient(app)


def test_routes_are_off_by_default() -> None:
    paths = {getattr(r, "path", "") for r in main_app.routes}
    assert "/api/llm/generate" not in paths


def test_generate_endpoint() -> None:
    client = client_with(FakeProvider("hello"))

    response = client.post("/api/llm/generate", json={"prompt": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["output"] == "hello"
    assert body["provider"] == "fake"
    assert body["usage"] == {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}


def test_minutes_endpoint_returns_structured_output() -> None:
    minutes = (
        '{"title": "Board", "attendees": ["Ama"], "decisions": ["ship"],'
        ' "action_items": [{"task": "send report", "owner": null}]}'
    )
    client = client_with(FakeProvider(minutes))

    response = client.post("/api/llm/minutes", json={"prompt": "transcript..."})

    assert response.status_code == 200
    assert response.json()["output"]["action_items"] == [{"task": "send report", "owner": None}]


def test_llm_errors_map_to_502() -> None:
    client = client_with(FakeProvider(error=LLMProviderError("quota exceeded")))

    response = client.post("/api/llm/generate", json={"prompt": "hi"})

    assert response.status_code == 502
    assert "quota exceeded" in response.json()["detail"]
