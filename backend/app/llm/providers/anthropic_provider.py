import anthropic
from anthropic.types import MessageParam

from app.llm.providers.base import Provider
from app.llm.types import (
    Completion,
    CompletionRequest,
    LLMProviderError,
    LLMRefusalError,
    Usage,
)


class AnthropicProvider(Provider):
    """Anthropic Messages API. Serves both the Claude API and Claude on Vertex AI."""

    def __init__(
        self, client: anthropic.Anthropic | anthropic.AnthropicVertex, name: str = "anthropic"
    ) -> None:
        super().__init__(name)
        self.client = client

    def complete(self, request: CompletionRequest) -> Completion:
        messages: list[MessageParam] = [
            {"role": "user", "content": m.content}
            if m.role == "user"
            else {"role": "assistant", "content": m.content}
            for m in request.messages
        ]
        system = request.system or anthropic.omit

        try:
            if request.schema is not None:
                response = self.client.messages.parse(
                    model=request.model,
                    max_tokens=request.max_tokens,
                    system=system,
                    messages=messages,
                    output_format=request.schema,
                )
            else:
                response = self.client.messages.create(
                    model=request.model,
                    max_tokens=request.max_tokens,
                    system=system,
                    messages=messages,
                )
        except anthropic.AnthropicError as e:
            raise LLMProviderError(f"{self.name} request failed: {e}") from e

        if response.stop_reason == "refusal":
            details = response.stop_details
            raise LLMRefusalError(
                f"model refused (category={details.category if details else None})"
            )

        u = response.usage
        return Completion(
            text="".join(b.text for b in response.content if b.type == "text"),
            usage=Usage(
                # input_tokens excludes cached tokens; add them back for the full prompt size.
                input_tokens=u.input_tokens
                + (u.cache_creation_input_tokens or 0)
                + (u.cache_read_input_tokens or 0),
                output_tokens=u.output_tokens,
            ),
        )
