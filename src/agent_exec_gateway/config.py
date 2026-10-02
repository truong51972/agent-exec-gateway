from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEG_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/aeg.db"
    bind_host: str = "127.0.0.1"
    port: int = 8000
    default_decision: str = Field(default="ask", pattern="^(allow|ask|deny)$")
    execution_timeout_seconds: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
