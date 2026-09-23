from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CloudPilot"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = (
        "postgresql+psycopg2://cloudpilot:cloudpilot@localhost:5432/cloudpilot"
    )

    # Comma-separated list of exact origins allowed by CORS (e.g. the deployed
    # Vercel production URL). Empty by default (deny all explicit origins) —
    # app/main.py additionally allows any https://*.vercel.app origin via
    # allow_origin_regex, which covers preview deployments without needing
    # this list updated for every branch.
    allowed_origins: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Display-only USD->INR rate — see app/services/currency.py. Every
    # persisted and computed monetary value in this system is USD; this
    # rate is used solely to reformat already-computed USD figures for
    # display, never as an input to any calculation.
    usd_to_inr_rate: float = 83.0

    @field_validator("database_url")
    @classmethod
    def _normalize_postgres_scheme(cls, value: str) -> str:
        # Render (and several other providers) hand out connection strings
        # using the legacy `postgres://` scheme, which SQLAlchemy 1.4+ no
        # longer accepts — it must be `postgresql://` (optionally with a
        # `+driver` suffix, which we leave alone if already present).
        if value.startswith("postgres://"):
            return "postgresql://" + value[len("postgres://") :]
        return value

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
