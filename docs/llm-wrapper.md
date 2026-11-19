# LLM wrapper

Issue #3. One interface for calling OpenAI, Gemini and Anthropic models, directly or through Vertex AI / Azure. Code lives in `backend/app/llm`.

Architecture diagram: [llm-wrapper-architecture.excalidraw](llm-wrapper-architecture.excalidraw) (open at excalidraw.com or with the VS Code Excalidraw extension).

## Usage

```python
from pydantic import BaseModel
from app.llm import get_llm_client

class Minutes(BaseModel):
    title: str
    action_items: list[str]

llm = get_llm_client()  # built once from env settings
reply = llm.generate("Summarise: ...", system="You are concise.")
minutes = llm.generate_structured("Extract the minutes: ...", schema=Minutes)
minutes.output        # validated Minutes instance
minutes.usage         # input / output / total tokens
```

Errors: `LLMProviderError` (SDK/network/auth), `LLMRefusalError` (safety block), `LLMOutputValidationError` (output didn't match the schema, `.raw_text` holds what came back). All inherit `LLMError`.

## Providers

Set `LLM_PROVIDER` and `LLM_MODEL`. Switching provider is a config change, not a code change.

| `LLM_PROVIDER` | Backend | SDK | Auth / extra config |
|---|---|---|---|
| `openai` | OpenAI API | `openai` | `LLM_API_KEY` |
| `azure` | Azure OpenAI (v1 API) | `openai` | `LLM_API_KEY`, `AZURE_ENDPOINT`; `LLM_MODEL` = deployment name |
| `gemini` | Gemini Developer API | `google-genai` | `LLM_API_KEY` |
| `vertex` | Gemini on Vertex AI | `google-genai` | ADC, `GCP_PROJECT`, `GCP_LOCATION` |
| `anthropic` | Claude API | `anthropic` | `LLM_API_KEY` |
| `anthropic_vertex` | Claude on Vertex AI | `anthropic[vertex]` | ADC, `GCP_PROJECT`, `GCP_LOCATION` |

## How Vertex AI and Azure fit in

- Neither needs its own adapter. Vertex AI and Azure host the same model families behind the same official SDKs; only the client constructor and auth change. The factory builds the right client and hands it to the shared adapter.
- **Vertex AI** (our default, since we deploy on GCP): no API key. Auth is Application Default Credentials: the VM's service account in prod, `gcloud auth application-default login` locally. Gemini is available out of the box. Claude models must be enabled per model in Model Garden. OpenAI's GPT models are not on Vertex. Note: Google now calls the Vertex AI API "Gemini Enterprise Agent Platform"; the SDK flag is `enterprise=True` (`vertexai=True` is the legacy name).
- **Azure**: Azure OpenAI is reached with the plain `openai` client pointed at `https://<resource>.openai.azure.com/openai/v1/`, using the model's deployment name. Key auth for now; Entra ID can be added in the factory later.

## Structured output

`generate_structured` uses each provider's native JSON-schema mode (OpenAI `response_format`, Gemini `response_json_schema`, Claude `output_format`), then validates the text with Pydantic in one place (`LLMClient`), so behaviour is identical across providers.

## Logging

Every call logs one line to the `app.llm` logger (container stdout): provider, model, schema, latency, input/output/total tokens, and a prompt preview truncated to `LLM_LOG_PROMPT_CHARS` (default 2000). Failures are logged with the traceback. Persisting usage to Postgres is planned for later.

## Trying it from the API

Set `LLM_TEST_ROUTES=true` (local only) and open `/api/docs`: `POST /api/llm/generate` returns text, `POST /api/llm/minutes` extracts a `MeetingMinutes` object from a pasted transcript. Both return provider, model, latency and token usage. Leave the flag off in deployed environments; the endpoints are unauthenticated and spend credits.

## Adding a provider

Write an adapter implementing `Provider.complete()` in `app/llm/providers/`, add a case in `factory.build_provider`, add the name to `LLMProviderName` in `config.py`.

## Not in scope yet

Async calls, streaming, retries beyond the SDKs' built-in ones, image/file inputs, and usage persistence.
