from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["openai", "azure", "gemini", "vertex", "anthropic", "anthropic_vertex"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dess:dess@localhost:5432/dess"
    files_dir: Path = Path("data/files")

    # LLM (see app/llm). Team default: Gemini API with an AI Studio key.
    # vertex / anthropic_vertex use GCP ADC, not llm_api_key.
    llm_provider: LLMProviderName = "gemini"
    llm_model: str = ""
    llm_api_key: str = ""
    # Gemini counts thinking tokens against this. OpenAI chat models may need a lower value.
    llm_max_tokens: int = 32768
    llm_log_prompt_chars: int = 2000
    gcp_project: str = ""
    gcp_location: str = "global"
    azure_endpoint: str = ""
    # Exposes /api/llm/* for manual testing. Keep off in prod: the endpoints spend LLM credits.
    llm_test_routes: bool = False

    # Minutes (see app/minutes). The API has no auth yet, so these routes expose client
    # material: keep off on public deployments until auth exists.
    minutes_routes: bool = False
    # Create missing tables on startup (no migrations yet).
    db_create_tables: bool = True

    # New: reads DATA_DIR from your .env, defaults to ./data
    data_dir: Path = Path("./data")

    @property
    def uploads_dir(self) -> Path:
        """Resolves to <DATA_DIR>/files/uploads."""
        return self.data_dir.resolve() / "files" / "uploads"


settings = Settings()
