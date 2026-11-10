from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["openai", "azure", "gemini", "vertex", "anthropic", "anthropic_vertex"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dess:dess@localhost:5432/dess"
    files_dir: Path = Path("data/files")

    # LLM (see app/llm). vertex / anthropic_vertex use GCP ADC, not llm_api_key.
    llm_provider: LLMProviderName = "vertex"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_max_tokens: int = 16000
    llm_log_prompt_chars: int = 2000
    gcp_project: str = ""
    gcp_location: str = "global"
    azure_endpoint: str = ""


settings = Settings()
