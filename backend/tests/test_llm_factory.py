from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.llm import build_llm_client
from app.llm import factory as llm_factory
from app.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"llm_model": "some-model", "llm_api_key": "test-key"}
    return Settings(_env_file=None, **(base | overrides))


@pytest.mark.parametrize(
    ("provider", "adapter", "extra"),
    [
        ("openai", OpenAIProvider, {}),
        ("azure", OpenAIProvider, {"azure_endpoint": "https://x.openai.azure.com/"}),
        ("gemini", GeminiProvider, {}),
        ("anthropic", AnthropicProvider, {}),
    ],
)
def test_builds_adapter_for_api_key_providers(
    provider: str, adapter: type, extra: dict[str, str]
) -> None:
    client = build_llm_client(make_settings(llm_provider=provider, **extra))

    assert isinstance(client.provider, adapter)
    assert client.provider.name == provider
    assert client.model == "some-model"


def test_azure_points_openai_client_at_v1_endpoint() -> None:
    client = build_llm_client(
        make_settings(llm_provider="azure", azure_endpoint="https://x.openai.azure.com/")
    )

    assert isinstance(client.provider, OpenAIProvider)
    assert str(client.provider.client.base_url) == "https://x.openai.azure.com/openai/v1/"


def test_vertex_uses_gcp_project_and_location(monkeypatch: pytest.MonkeyPatch) -> None:
    genai_client = MagicMock()
    monkeypatch.setattr(llm_factory.genai, "Client", genai_client)

    client = build_llm_client(
        make_settings(llm_provider="vertex", gcp_project="proj", gcp_location="europe-west2")
    )

    assert client.provider.name == "vertex"
    kwargs = genai_client.call_args.kwargs
    assert (kwargs["enterprise"], kwargs["project"], kwargs["location"]) == (
        True,
        "proj",
        "europe-west2",
    )
    assert kwargs["http_options"].timeout == 600_000
    assert kwargs["http_options"].retry_options.http_status_codes == [429, 500, 503]


def test_anthropic_vertex_uses_gcp_project_and_region(monkeypatch: pytest.MonkeyPatch) -> None:
    vertex_client = MagicMock()
    monkeypatch.setattr(llm_factory.anthropic, "AnthropicVertex", vertex_client)

    client = build_llm_client(make_settings(llm_provider="anthropic_vertex", gcp_project="proj"))

    assert client.provider.name == "anthropic_vertex"
    vertex_client.assert_called_once_with(project_id="proj", region="global", timeout=600)


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"llm_provider": "openai", "llm_model": ""}, "LLM_MODEL"),
        ({"llm_provider": "vertex"}, "GCP_PROJECT"),
        ({"llm_provider": "azure"}, "AZURE_ENDPOINT"),
    ],
)
def test_missing_required_settings_raise(overrides: dict[str, str], missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        build_llm_client(make_settings(**overrides))
