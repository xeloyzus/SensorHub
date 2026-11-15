"""Application settings, loaded from environment variables (and ``.env``)."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Field names map to UPPERCASE environment vars."""

    # Validated before the API starts accepting requests.
    database_url: str | None = None
    display_refresh_seconds: int = Field(default=60, ge=10, le=3600)
    public_base_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def runtime_mode(self) -> str:
        return "live"

    @property
    def data_source(self) -> str:
        return "timescaledb"

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path
                or any(character.isspace() for character in value)):
            raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) origin without credentials, a path, or a query")
        parsed.port  # Reject invalid ports.
        return value

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required.")
        return self.database_url


settings = Settings()
