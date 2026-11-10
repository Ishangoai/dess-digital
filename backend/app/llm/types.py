"""Provider-agnostic request/response types shared by the LLM client and its providers."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CompletionRequest:
    """What the client hands to a provider. `schema` set means structured (JSON) output."""

    model: str
    messages: list[Message]
    max_tokens: int
    system: str | None = None
    schema: type[BaseModel] | None = None


@dataclass(frozen=True)
class Completion:
    """What a provider hands back: the raw text (JSON when a schema was requested) and usage."""

    text: str
    usage: Usage


@dataclass(frozen=True)
class LLMResponse[T]:
    """Returned to callers. `output` is `str` for text calls or the validated schema instance."""

    output: T
    text: str
    usage: Usage
    provider: str
    model: str
    latency_ms: float


class LLMError(Exception):
    """Base class for every error raised by the LLM wrapper."""


class LLMProviderError(LLMError):
    """The provider SDK failed (auth, rate limit, network, bad request...). See `__cause__`."""


class LLMRefusalError(LLMError):
    """The model or provider safety filter declined to answer."""


class LLMOutputValidationError(LLMError):
    """The model's output did not match the requested schema."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text
