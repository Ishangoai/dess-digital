from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolves to `<repo>/backend/data` when DATA_DIR is unset
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dess:dess@localhost:5432/dess"

    # LLM: vertex | bedrock | azure
    llm_provider: str = "vertex"
    llm_model: str = ""
    llm_api_key: str = ""

    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"
    
    @property
    def uploads_dir(self) -> Path:
        """Resolves to the persisted mount: /data/files/uploads."""
        return self.files_dir / "uploads"


settings = Settings()
