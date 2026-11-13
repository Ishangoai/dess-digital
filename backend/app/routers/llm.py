"""Manual test endpoints for the LLM wrapper. Mounted only when LLM_TEST_ROUTES=true."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.llm import LLMClient, LLMError, LLMResponse, get_llm_client

router = APIRouter(prefix="/llm", tags=["llm (test)"])

Client = Annotated[LLMClient, Depends(get_llm_client)]


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    system: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ActionItem(BaseModel):
    task: str
    owner: str | None


class MeetingMinutes(BaseModel):
    """Example schema for exercising structured output."""

    title: str
    attendees: list[str]
    decisions: list[str]
    action_items: list[ActionItem]


class GenerateResponse[T](BaseModel):
    output: T
    provider: str
    model: str
    latency_ms: float
    usage: UsageOut


@router.post("/generate")
def generate(body: GenerateRequest, llm: Client) -> GenerateResponse[str]:
    return _to_response(
        _run(lambda: llm.generate(body.prompt, system=body.system, max_tokens=body.max_tokens))
    )


@router.post("/minutes")
def minutes(body: GenerateRequest, llm: Client) -> GenerateResponse[MeetingMinutes]:
    """Extract MeetingMinutes from the prompt text (e.g. a pasted meeting transcript)."""
    return _to_response(
        _run(
            lambda: llm.generate_structured(
                body.prompt,
                schema=MeetingMinutes,
                system=body.system or "Extract the meeting minutes from the transcript.",
                max_tokens=body.max_tokens,
            )
        )
    )


def _run[T](call: Callable[[], LLMResponse[T]]) -> LLMResponse[T]:
    try:
        return call()
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e


def _to_response[T](r: LLMResponse[T]) -> GenerateResponse[T]:
    return GenerateResponse[T](
        output=r.output,
        provider=r.provider,
        model=r.model,
        latency_ms=round(r.latency_ms, 1),
        usage=UsageOut(
            input_tokens=r.usage.input_tokens,
            output_tokens=r.usage.output_tokens,
            total_tokens=r.usage.total_tokens,
        ),
    )
