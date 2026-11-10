from abc import ABC, abstractmethod

from app.llm.types import Completion, CompletionRequest


class Provider(ABC):
    """One adapter per SDK. Adapters translate a CompletionRequest into a native call.

    Adapters receive an already-built SDK client, so the same adapter serves the direct API
    and the cloud-hosted variant (e.g. Gemini API vs Vertex AI, OpenAI vs Azure OpenAI).
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def complete(self, request: CompletionRequest) -> Completion:
        """Run one completion. Raise LLMProviderError / LLMRefusalError on failure."""
