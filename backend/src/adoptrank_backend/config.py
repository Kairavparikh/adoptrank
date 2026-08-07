from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_token: str | None = None
    database_url: str | None = None
    model_dir: Path = Path("artifacts/current")
    ranker_api_key: str | None = None
    github_api_url: str = "https://api.github.com"
    request_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
