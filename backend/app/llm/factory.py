from functools import cache

import anthropic
import openai
from google import genai
from google.genai import types

from app.config import Settings, settings
from app.llm.client import LLMClient
from app.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider, Provider


def build_provider(cfg: Settings) -> Provider:
    """Map LLM_PROVIDER to an adapter wrapping the right SDK client.

    Cloud-hosted variants (Vertex, Azure) reuse the same adapter as the direct API;
    only the client construction and auth differ.
    """
    match cfg.llm_provider:
        case "openai":
            client = openai.OpenAI(api_key=cfg.llm_api_key or None, timeout=cfg.llm_timeout_seconds)
            return OpenAIProvider(client, "openai")
        case "azure":
            # Azure OpenAI v1 API: plain OpenAI client pointed at the resource; model = deployment.
            endpoint = _require(cfg.azure_endpoint, "AZURE_ENDPOINT").rstrip("/")
            client = openai.OpenAI(
                api_key=_require(cfg.llm_api_key, "LLM_API_KEY"),
                base_url=f"{endpoint}/openai/v1/",
                timeout=cfg.llm_timeout_seconds,
            )
            return OpenAIProvider(client, "azure")
        case "gemini":
            client = genai.Client(api_key=cfg.llm_api_key or None, http_options=_gemini_http(cfg))
            return GeminiProvider(client, "gemini")
        case "vertex":
            # Auth via Application Default Credentials (VM service account / gcloud locally).
            client = genai.Client(
                enterprise=True,
                project=_require(cfg.gcp_project, "GCP_PROJECT"),
                location=cfg.gcp_location,
                http_options=_gemini_http(cfg),
            )
            return GeminiProvider(client, "vertex")
        case "anthropic":
            client = anthropic.Anthropic(
                api_key=cfg.llm_api_key or None, timeout=cfg.llm_timeout_seconds
            )
            return AnthropicProvider(client, "anthropic")
        case "anthropic_vertex":
            client = anthropic.AnthropicVertex(
                project_id=_require(cfg.gcp_project, "GCP_PROJECT"),
                region=cfg.gcp_location,
                timeout=cfg.llm_timeout_seconds,
            )
            return AnthropicProvider(client, "anthropic_vertex")


def build_llm_client(cfg: Settings) -> LLMClient:
    return LLMClient(
        build_provider(cfg),
        _require(cfg.llm_model, "LLM_MODEL"),
        max_tokens=cfg.llm_max_tokens,
        log_prompt_chars=cfg.llm_log_prompt_chars,
    )


@cache
def get_llm_client() -> LLMClient:
    """Process-wide client built from env settings."""
    return build_llm_client(settings)


def _gemini_http(cfg: Settings) -> types.HttpOptions:
    # Without a timeout an overloaded model can stall a request indefinitely.
    retry = types.HttpRetryOptions(
        attempts=5, initial_delay=5, max_delay=60, http_status_codes=[429, 500, 503]
    )
    return types.HttpOptions(timeout=cfg.llm_timeout_seconds * 1000, retry_options=retry)


def _require(value: str, env_name: str) -> str:
    if not value:
        raise ValueError(f"{env_name} must be set for LLM_PROVIDER in use")
    return value
