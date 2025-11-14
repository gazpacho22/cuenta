"""Typed configuration loader for the expense bot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings using Pydantic's BaseSettings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_token: SecretStr = Field(alias="TELEGRAM_TOKEN")
    telegram_webhook_secret: str | None = Field(
        default=None, alias="TELEGRAM_WEBHOOK_SECRET"
    )
    telegram_allowed_users: list[int] = Field(
        default_factory=list, alias="TELEGRAM_ALLOWED_USERS"
    )

    erp_base_url: str = Field(alias="ERP_BASE_URL")
    erp_api_key: SecretStr = Field(alias="ERP_API_KEY")
    erp_api_secret: SecretStr = Field(alias="ERP_API_SECRET")
    default_company: str = Field(alias="DEFAULT_COMPANY")
    default_currency: str = Field(default="USD", alias="DEFAULT_CURRENCY")

    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    checkpoint_db: Path = Field(
        default=Path("var/checkpoints/expense_bot.sqlite"), alias="CHECKPOINT_DB"
    )
    retry_db: Path = Field(
        default=Path("var/checkpoints/retry_jobs.sqlite"), alias="RETRY_DB"
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("telegram_allowed_users", mode="before")
    @classmethod
    def _parse_allowed_users(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            chunks = [chunk.strip() for chunk in value.split(",")]
            return [int(chunk) for chunk in chunks if chunk]
        if isinstance(value, Iterable):
            return [int(item) for item in value]
        raise TypeError("TELEGRAM_ALLOWED_USERS must be a CSV string or list")

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: str | None) -> str:
        return (value or "INFO").upper()

    @field_validator("erp_base_url", mode="after")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


__all__ = ["Settings", "get_settings"]
