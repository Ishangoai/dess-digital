"""Single interface for calling LLM providers.

from app.llm import get_llm_client

llm = get_llm_client()
reply = llm.generate("Summarise this document: ...")
minutes = llm.generate_structured("Extract the minutes: ...", schema=Minutes)
minutes.output  # validated Minutes instance
"""

from app.llm.client import LLMClient
from app.llm.factory import build_llm_client, get_llm_client
from app.llm.types import (
    LLMError,
    LLMOutputValidationError,
    LLMProviderError,
    LLMRefusalError,
    LLMResponse,
    Message,
    Usage,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMOutputValidationError",
    "LLMProviderError",
    "LLMRefusalError",
    "LLMResponse",
    "Message",
    "Usage",
    "build_llm_client",
    "get_llm_client",
]
