"""Runtime configuration. Everything is overridable by environment variable."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kira:kira@localhost:5432/kira"
    jwt_secret: str = "development-only-replace-with-a-secure-jwt-secret"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]

    # Pins "today" so the seeded demo produces the same numbers on any date.
    # Unset in real use, in which case the server's UTC date is used.
    demo_today: date | None = None

    # ── Butler ────────────────────────────────────────────────────────────────
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    butler_model: str = "qwen-plus"
    # Forced offline; the Butler also falls back on a missing key or a failed call.
    butler_offline: bool = False
    butler_max_tool_iterations: int = 6
    butler_request_timeout_seconds: float = 30.0
    butler_memory_limit: int = 40
    # Voice and camera capture. Off means the affordances stay hidden rather
    # than pretending to work; the adapters behind them are chosen in the
    # adapter registry, not here.
    capture_receipt_enabled: bool = True
    capture_voice_enabled: bool = True
    capture_max_bytes: int = 8 * 1024 * 1024

    @property
    def checkpointer_dsn(self) -> str:
        """LangGraph's Postgres checkpointer runs on psycopg3, not asyncpg.

        Same database, second driver: the SQLAlchemy dialect suffix has to go.
        """
        return self.database_url.replace("+asyncpg", "").replace("+psycopg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
