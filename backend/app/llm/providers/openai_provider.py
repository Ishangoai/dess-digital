import openai
from openai.types.chat import ChatCompletionMessageParam

from app.llm.providers.base import Provider
from app.llm.types import (
    Completion,
    CompletionRequest,
    LLMProviderError,
    LLMRefusalError,
    Usage,
)


class OpenAIProvider(Provider):
    """OpenAI Chat Completions. Also serves Azure OpenAI (same SDK, different base URL)."""

    def __init__(self, client: openai.OpenAI, name: str = "openai") -> None:
        super().__init__(name)
        self.client = client

    def complete(self, request: CompletionRequest) -> Completion:
        messages: list[ChatCompletionMessageParam] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for m in request.messages:
            if m.role == "user":
                messages.append({"role": "user", "content": m.content})
            else:
                messages.append({"role": "assistant", "content": m.content})

        try:
            if request.schema is not None:
                response = self.client.chat.completions.parse(
                    model=request.model,
                    messages=messages,
                    max_completion_tokens=request.max_tokens,
                    response_format=request.schema,
                )
            else:
                response = self.client.chat.completions.create(
                    model=request.model,
                    messages=messages,
                    max_completion_tokens=request.max_tokens,
                )
        except openai.OpenAIError as e:
            raise LLMProviderError(f"{self.name} request failed: {e}") from e

        message = response.choices[0].message
        if message.refusal:
            raise LLMRefusalError(message.refusal)

        usage = response.usage
        return Completion(
            text=message.content or "",
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
        )
