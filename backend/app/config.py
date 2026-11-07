from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dess:dess@localhost:5432/dess"
    files_dir: Path = Path("data/files")

    # LLM: vertex | bedrock | azure
    llm_provider: str = "vertex"
    llm_model: str = ""
    llm_api_key: str = ""


settings = Settings()
