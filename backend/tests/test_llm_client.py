import logging

import pytest
from pydantic import BaseModel

from app.llm import LLMClient, LLMOutputValidationError, LLMProviderError, Message
from app.llm.providers.base import Provider
from app.llm.types import Completion, CompletionRequest, Usage


class Minutes(BaseModel):
    title: str
    action_items: list[str]


class FakeProvider(Provider):
    def __init__(self, text: str = "hello", error: Exception | None = None) -> None:
        super().__init__("fake")
        self.text = text
        self.error = error
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        if self.error:
            raise self.error
        return Completion(text=self.text, usage=Usage(input_tokens=12, output_tokens=5))


def test_generate_returns_text_and_usage() -> None:
    provider = FakeProvider("hi there")
    client = LLMClient(provider, "fake-model", max_tokens=100)

    response = client.generate("say hi", system="be brief")

    assert response.output == "hi there"
    assert response.usage.total_tokens == 17
    assert response.provider == "fake"
    assert response.model == "fake-model"
    request = provider.requests[0]
    assert request.messages == [Message("user", "say hi")]
    assert request.system == "be brief"
    assert request.max_tokens == 100
    assert request.schema is None


def test_generate_accepts_message_history_and_max_tokens_override() -> None:
    provider = FakeProvider()
    client = LLMClient(provider, "fake-model", max_tokens=100)
    history = [Message("user", "a"), Message("assistant", "b"), Message("user", "c")]

    client.generate(history, max_tokens=5)

    assert provider.requests[0].messages == history
    assert provider.requests[0].max_tokens == 5


def test_generate_structured_validates_into_schema() -> None:
    provider = FakeProvider('{"title": "Board meeting", "action_items": ["send report"]}')
    client = LLMClient(provider, "fake-model")

    response = client.generate_structured("extract", schema=Minutes)

    assert response.output == Minutes(title="Board meeting", action_items=["send report"])
    assert provider.requests[0].schema is Minutes


def test_generate_structured_raises_on_invalid_output() -> None:
    provider = FakeProvider('{"title": "missing items"}')
    client = LLMClient(provider, "fake-model")

    with pytest.raises(LLMOutputValidationError) as exc:
        client.generate_structured("extract", schema=Minutes)

    assert exc.value.raw_text == '{"title": "missing items"}'


def test_logs_prompt_and_token_usage(caplog: pytest.LogCaptureFixture) -> None:
    client = LLMClient(FakeProvider(), "fake-model", log_prompt_chars=10)

    with caplog.at_level(logging.INFO, logger="app.llm"):
        client.generate("0123456789abcdef")

    (record,) = caplog.records
    message = record.getMessage()
    assert "provider=fake model=fake-model" in message
    assert "input_tokens=12 output_tokens=5 total_tokens=17" in message
    assert "[user] 012... [13 more chars]" in message


def test_logs_and_reraises_provider_errors(caplog: pytest.LogCaptureFixture) -> None:
    client = LLMClient(FakeProvider(error=LLMProviderError("boom")), "fake-model")

    with caplog.at_level(logging.INFO, logger="app.llm"), pytest.raises(LLMProviderError):
        client.generate("hi")

    assert caplog.records[0].levelno == logging.ERROR
    assert "llm call failed provider=fake" in caplog.records[0].getMessage()
