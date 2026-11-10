from pydantic import BaseModel

from app.llm.providers.base import Provider
from app.llm.types import Completion, CompletionRequest, Usage


class ScriptedProvider(Provider):
    """Returns a canned output per requested schema name; records every request."""

    def __init__(self, responses: dict[str, BaseModel | str | Exception]) -> None:
        super().__init__("scripted")
        self.responses = responses
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        name = request.schema.__name__ if request.schema else "text"
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        text = response.model_dump_json() if isinstance(response, BaseModel) else response
        return Completion(text=text, usage=Usage(input_tokens=100, output_tokens=10))

    def schemas_called(self) -> list[str]:
        return [r.schema.__name__ if r.schema else "text" for r in self.requests]
