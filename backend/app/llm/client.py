import logging
import time
from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from app.llm.providers.base import Provider
from app.llm.types import (
    Completion,
    CompletionRequest,
    LLMOutputValidationError,
    LLMResponse,
    Message,
)

log = logging.getLogger("app.llm")

Prompt = str | Sequence[Message]


class LLMClient:
    """The one interface the rest of the app uses to call an LLM.

    Every call is logged with provider, model, latency, token usage and a prompt preview.
    """

    def __init__(
        self,
        provider: Provider,
        model: str,
        *,
        max_tokens: int = 16000,
        log_prompt_chars: int = 2000,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.log_prompt_chars = log_prompt_chars

    def generate(
        self, prompt: Prompt, *, system: str | None = None, max_tokens: int | None = None
    ) -> LLMResponse[str]:
        """Plain text completion."""
        request = self._request(prompt, system, max_tokens, schema=None)
        completion, latency_ms = self._call(request)
        return self._response(completion.text, completion, latency_ms)

    def generate_structured[T: BaseModel](
        self,
        prompt: Prompt,
        schema: type[T],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse[T]:
        """Completion constrained to `schema`, returned as a validated `schema` instance."""
        request = self._request(prompt, system, max_tokens, schema=schema)
        completion, latency_ms = self._call(request)
        try:
            output = schema.model_validate_json(completion.text)
        except ValidationError as e:
            log.error(
                "llm output failed validation provider=%s model=%s schema=%s errors=%s",
                self.provider.name,
                self.model,
                schema.__name__,
                e.errors(include_url=False),
            )
            raise LLMOutputValidationError(
                f"output does not match {schema.__name__}", completion.text
            ) from e
        return self._response(output, completion, latency_ms)

    def _request(
        self,
        prompt: Prompt,
        system: str | None,
        max_tokens: int | None,
        schema: type[BaseModel] | None,
    ) -> CompletionRequest:
        messages = [Message("user", prompt)] if isinstance(prompt, str) else list(prompt)
        return CompletionRequest(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            system=system,
            schema=schema,
        )

    def _call(self, request: CompletionRequest) -> tuple[Completion, float]:
        schema_name = request.schema.__name__ if request.schema else None
        start = time.perf_counter()
        try:
            completion = self.provider.complete(request)
        except Exception as e:
            log.exception(
                "llm call failed provider=%s model=%s schema=%s latency_ms=%.0f prompt=%r",
                self.provider.name,
                request.model,
                schema_name,
                (time.perf_counter() - start) * 1000,
                self._prompt_preview(request),
            )
            if isinstance(e, ValidationError):
                # SDK .parse() helpers (OpenAI, Anthropic) validate inside the call, before the
                # adapter's truncation/refusal checks, so a pydantic error can escape the adapter.
                raise LLMOutputValidationError(
                    f"{self.provider.name} output does not match {schema_name}", ""
                ) from e
            raise
        latency_ms = (time.perf_counter() - start) * 1000

        usage = completion.usage
        log.info(
            "llm call provider=%s model=%s schema=%s latency_ms=%.0f "
            "input_tokens=%d output_tokens=%d total_tokens=%d prompt=%r",
            self.provider.name,
            request.model,
            schema_name,
            latency_ms,
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
            self._prompt_preview(request),
        )
        return completion, latency_ms

    def _prompt_preview(self, request: CompletionRequest) -> str:
        parts = [f"[system] {request.system}"] if request.system else []
        parts += [f"[{m.role}] {m.content}" for m in request.messages]
        text = "\n".join(parts)
        limit = self.log_prompt_chars
        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [{len(text) - limit} more chars]"

    def _response[T](self, output: T, completion: Completion, latency_ms: float) -> LLMResponse[T]:
        return LLMResponse(
            output=output,
            text=completion.text,
            usage=completion.usage,
            provider=self.provider.name,
            model=self.model,
            latency_ms=latency_ms,
        )
