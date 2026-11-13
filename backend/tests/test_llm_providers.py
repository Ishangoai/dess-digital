"""Adapter tests against mocked SDK clients: request mapping and usage/refusal parsing."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import openai
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from app.llm import LLMProviderError, LLMRefusalError, LLMTruncatedError, Message
from app.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider
from app.llm.types import CompletionRequest


class Answer(BaseModel):
    value: int


def make_request(schema: type[BaseModel] | None = None) -> CompletionRequest:
    return CompletionRequest(
        model="m",
        messages=[Message("user", "q"), Message("assistant", "a"), Message("user", "q2")],
        max_tokens=50,
        system="sys",
        schema=schema,
    )


# --- OpenAI / Azure ---------------------------------------------------------


def openai_response(
    content: str | None, refusal: str | None = None, finish_reason: str = "stop"
) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_openai_text() -> None:
    client: Any = MagicMock()
    client.chat.completions.create.return_value = openai_response("hi")

    completion = OpenAIProvider(client).complete(make_request())

    assert completion.text == "hi"
    assert (completion.usage.input_tokens, completion.usage.output_tokens) == (7, 3)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert [m["role"] for m in kwargs["messages"]] == ["system", "user", "assistant", "user"]
    assert kwargs["max_completion_tokens"] == 50


def test_openai_structured_uses_parse() -> None:
    client: Any = MagicMock()
    client.chat.completions.parse.return_value = openai_response('{"value": 1}')

    completion = OpenAIProvider(client).complete(make_request(Answer))

    assert completion.text == '{"value": 1}'
    assert client.chat.completions.parse.call_args.kwargs["response_format"] is Answer


def test_openai_refusal() -> None:
    client: Any = MagicMock()
    client.chat.completions.create.return_value = openai_response(None, refusal="no")

    with pytest.raises(LLMRefusalError):
        OpenAIProvider(client).complete(make_request())


def test_openai_truncation() -> None:
    client: Any = MagicMock()
    client.chat.completions.create.return_value = openai_response("partial", finish_reason="length")

    with pytest.raises(LLMTruncatedError):
        OpenAIProvider(client).complete(make_request())


def test_openai_sdk_error_is_wrapped() -> None:
    client: Any = MagicMock()
    client.chat.completions.create.side_effect = openai.OpenAIError("down")

    with pytest.raises(LLMProviderError):
        OpenAIProvider(client).complete(make_request())


# --- Gemini / Vertex --------------------------------------------------------


def gemini_response(
    text: str,
    block_reason: str | None = None,
    finish_reason: genai_types.FinishReason = genai_types.FinishReason.STOP,
) -> Any:
    usage = SimpleNamespace(prompt_token_count=8, candidates_token_count=2, thoughts_token_count=4)
    feedback = SimpleNamespace(block_reason=block_reason) if block_reason else None
    return SimpleNamespace(
        text=text,
        usage_metadata=usage,
        prompt_feedback=feedback,
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )


def test_gemini_text() -> None:
    client: Any = MagicMock()
    client.models.generate_content.return_value = gemini_response("hi")

    completion = GeminiProvider(client).complete(make_request())

    assert completion.text == "hi"
    assert (completion.usage.input_tokens, completion.usage.output_tokens) == (8, 6)
    kwargs = client.models.generate_content.call_args.kwargs
    assert [c.role for c in kwargs["contents"]] == ["user", "model", "user"]
    assert kwargs["config"].system_instruction == "sys"
    assert kwargs["config"].response_json_schema is None


def test_gemini_structured_sets_json_schema() -> None:
    client: Any = MagicMock()
    client.models.generate_content.return_value = gemini_response('{"value": 1}')

    GeminiProvider(client).complete(make_request(Answer))

    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == Answer.model_json_schema()


def test_gemini_blocked_prompt() -> None:
    client: Any = MagicMock()
    client.models.generate_content.return_value = gemini_response("", block_reason="SAFETY")

    with pytest.raises(LLMRefusalError):
        GeminiProvider(client).complete(make_request())


def test_gemini_truncation() -> None:
    client: Any = MagicMock()
    client.models.generate_content.return_value = gemini_response(
        '{"value": ', finish_reason=genai_types.FinishReason.MAX_TOKENS
    )

    with pytest.raises(LLMTruncatedError):
        GeminiProvider(client).complete(make_request(Answer))


def test_gemini_blocked_response() -> None:
    client: Any = MagicMock()
    client.models.generate_content.return_value = gemini_response(
        "", finish_reason=genai_types.FinishReason.SAFETY
    )

    with pytest.raises(LLMRefusalError):
        GeminiProvider(client).complete(make_request())


def test_gemini_sdk_error_is_wrapped() -> None:
    client: Any = MagicMock()
    client.models.generate_content.side_effect = genai_errors.APIError(500, {"error": {}})

    with pytest.raises(LLMProviderError):
        GeminiProvider(client).complete(make_request())


# --- Anthropic / Claude on Vertex -------------------------------------------


def anthropic_response(text: str, stop_reason: str = "end_turn") -> Any:
    usage = SimpleNamespace(
        input_tokens=5,
        output_tokens=9,
        cache_creation_input_tokens=1,
        cache_read_input_tokens=None,
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=usage,
        stop_reason=stop_reason,
        stop_details=None,
    )


def test_anthropic_text() -> None:
    client: Any = MagicMock()
    client.messages.create.return_value = anthropic_response("hi")

    completion = AnthropicProvider(client).complete(make_request())

    assert completion.text == "hi"
    assert (completion.usage.input_tokens, completion.usage.output_tokens) == (6, 9)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == "sys"
    assert [m["role"] for m in kwargs["messages"]] == ["user", "assistant", "user"]
    assert kwargs["max_tokens"] == 50


def test_anthropic_structured_uses_parse() -> None:
    client: Any = MagicMock()
    client.messages.parse.return_value = anthropic_response('{"value": 1}')

    completion = AnthropicProvider(client).complete(make_request(Answer))

    assert completion.text == '{"value": 1}'
    assert client.messages.parse.call_args.kwargs["output_format"] is Answer


def test_anthropic_refusal() -> None:
    client: Any = MagicMock()
    client.messages.create.return_value = anthropic_response("", stop_reason="refusal")

    with pytest.raises(LLMRefusalError):
        AnthropicProvider(client).complete(make_request())


def test_anthropic_truncation() -> None:
    client: Any = MagicMock()
    client.messages.create.return_value = anthropic_response("partial", stop_reason="max_tokens")

    with pytest.raises(LLMTruncatedError):
        AnthropicProvider(client).complete(make_request())


def test_anthropic_sdk_error_is_wrapped() -> None:
    client: Any = MagicMock()
    client.messages.create.side_effect = anthropic.AnthropicError("down")

    with pytest.raises(LLMProviderError):
        AnthropicProvider(client).complete(make_request())
