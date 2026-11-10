from google import genai
from google.genai import errors, types

from app.llm.providers.base import Provider
from app.llm.types import (
    Completion,
    CompletionRequest,
    LLMProviderError,
    LLMRefusalError,
    Usage,
)


class GeminiProvider(Provider):
    """Google Gen AI SDK. Serves both the Gemini Developer API and Vertex AI."""

    def __init__(self, client: genai.Client, name: str = "gemini") -> None:
        super().__init__(name)
        self.client = client

    def complete(self, request: CompletionRequest) -> Completion:
        contents = [
            types.Content(
                role="user" if m.role == "user" else "model",
                parts=[types.Part(text=m.content)],
            )
            for m in request.messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            max_output_tokens=request.max_tokens,
        )
        if request.schema is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = request.schema.model_json_schema()

        try:
            response = self.client.models.generate_content(
                model=request.model, contents=contents, config=config
            )
        except errors.APIError as e:
            raise LLMProviderError(f"{self.name} request failed: {e}") from e

        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason is not None:
            raise LLMRefusalError(f"prompt blocked: {feedback.block_reason}")

        meta = response.usage_metadata
        return Completion(
            text=response.text or "",
            usage=Usage(
                input_tokens=(meta.prompt_token_count or 0) if meta else 0,
                # Thinking tokens are billed as output.
                output_tokens=(
                    (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
                    if meta
                    else 0
                ),
            ),
        )
