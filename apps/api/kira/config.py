"""Runtime configuration. Everything is overridable by environment variable."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kira:kira@localhost:5432/kira"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]

    # Pins "today" so the seeded demo produces the same numbers on any date.
    # Unset in real use, in which case the server's UTC date is used.
    demo_today: date | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
