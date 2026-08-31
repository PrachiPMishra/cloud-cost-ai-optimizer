from functools import lru_cache

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

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Display-only USD->INR rate — see app/services/currency.py. Every
    # persisted and computed monetary value in this system is USD; this
    # rate is used solely to reformat already-computed USD figures for
    # display, never as an input to any calculation.
    usd_to_inr_rate: float = 83.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
