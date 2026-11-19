from collections.abc import Callable

from pydantic import BaseModel

from app.llm.providers.base import Provider
from app.llm.types import Completion, CompletionRequest, Usage


class ScriptedProvider(Provider):
    """Returns a canned output per requested schema name; records every request.

    A response may be a function of the request, for schemas called once per item.
    """

    def __init__(self, responses: dict[str, "Response"]) -> None:
        super().__init__("scripted")
        self.responses = responses
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        name = request.schema.__name__ if request.schema else "text"
        response = self.responses[name]
        result = response(request) if callable(response) else response
        if isinstance(result, Exception):
            raise result
        text = result.model_dump_json() if isinstance(result, BaseModel) else str(result)
        return Completion(text=text, usage=Usage(input_tokens=100, output_tokens=10))

    def schemas_called(self) -> list[str]:
        return [r.schema.__name__ if r.schema else "text" for r in self.requests]


Response = BaseModel | str | Exception | Callable[[CompletionRequest], BaseModel | str | Exception]
