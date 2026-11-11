from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dess:dess@localhost:5432/dess"

    files_dir: Path = Path("/data/files")

    # LLM: vertex | bedrock | azure
    llm_provider: str = "vertex"
    llm_model: str = ""
    llm_api_key: str = ""

    # New: reads DATA_DIR from your .env, defaults to ./data
    data_dir: Path = Path("./data")

    @property
    def uploads_dir(self) -> Path:
        """Resolves to the persisted mount: /data/files/uploads."""
        return self.files_dir / "uploads"


settings = Settings()
