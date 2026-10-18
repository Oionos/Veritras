import os
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator


class Settings(BaseSettings):
    environment: str = Field(default="development")
    database_url: str = Field(default="sqlite:///./veritras.db", repr=False)
    # Plural form — preferred. Falls back to cors_origin if empty.
    cors_origins: str = Field(default="")
    # Singular form — backward compatibility for Render Dashboard configs.
    cors_origin: str = Field(default="http://localhost:5173")
    sepolia_rpc_url: str = Field(default="", repr=False)
    product_registry_contract: str = Field(default="")
    shipment_tracker_contract: str = Field(default="")
    indexer_poll_interval: int = Field(default=15)
    indexer_start_block: int = Field(default=0)
    chain_id: int = Field(default=11155111)
    indexer_enabled: bool = Field(default=True)
    indexer_rpc_timeout: int = Field(default=10, ge=1)
    indexer_retry_interval: int = Field(default=5, ge=1)
    indexer_batch_size: int = Field(default=1000, ge=1, le=10000)
    indexer_stale_after: int = Field(default=120, ge=1)
    indexer_state_path: str = Field(default="")  # Deprecated: file cursors are never trusted.
    indexer_confirmations: int = Field(default=12, ge=0, le=256)
    indexer_max_reorg_depth: int = Field(default=2048, ge=1, le=100000)
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    jwt_secret_key: str = Field(default="dev-secret-change-in-production", repr=False)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_expiration_hours: int = Field(default=24, ge=1, le=24)
    jwt_issuer: str = "veritras-api"
    jwt_audience: str = "veritras-web"
    siwe_origins: str = ""
    auth_challenge_ttl_seconds: int = Field(default=300, ge=60, le=600)
    auth_clock_skew_seconds: int = Field(default=30, ge=0, le=60)

    @field_validator("database_url", mode="before")
    @classmethod
    def use_installed_postgres_driver(cls, value):
        # SQLAlchemy's default PostgreSQL driver changes across major versions.
        # The project explicitly installs psycopg2-binary.
        if isinstance(value, str):
            for prefix in ("postgres://", "postgresql://"):
                if value.startswith(prefix):
                    return "postgresql+psycopg2://" + value[len(prefix):]
        return value

    @model_validator(mode="after")
    def validate_environment(self):
        if self.environment.lower() not in {"development", "testing", "production"}:
            raise ValueError("ENVIRONMENT must be development, testing, or production")
        if self.is_hosted:
            placeholder = self.jwt_secret_key.lower().startswith(("dev-secret", "replace", "change-me", "your_", "your-"))
            local_key_on_hosted_chain = self.chain_id != 31337 and self.jwt_secret_key.startswith("local-testing-only")
            if len(self.jwt_secret_key) < 32 or placeholder or local_key_on_hosted_chain:
                raise ValueError("An explicit JWT_SECRET_KEY of at least 32 characters is required")
        if self.environment.lower() == "testing":
            live = {"0x1f76018532d619194f6628adc186e3c86fcb5aaa", "0x95b09c0aed53f6b63c072f4ecac18861fcbbfb30"}
            if self.product_registry_contract.lower() in live or self.shipment_tracker_contract.lower() in live:
                raise ValueError("Testing must use separate contract addresses")
        self.allowed_siwe_origins
        return self

    @property
    def allowed_siwe_origins(self) -> list[str]:
        values = (self.siwe_origins or self.effective_cors_origins).split(",")
        origins = []
        for value in values:
            origin = value.strip().rstrip("/")
            if not origin:
                continue
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                    or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment or "*" in origin):
                raise ValueError("SIWE_ORIGINS must contain exact HTTP(S) origins")
            if self.is_hosted and self.chain_id != 31337 and parsed.scheme != "https":
                raise ValueError("Hosted wallet sign-in requires HTTPS origins")
            origins.append(origin)
        if not origins:
            raise ValueError("Configure at least one SIWE_ORIGINS origin")
        return origins

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_hosted(self) -> bool:
        return self.environment.lower() in {"production", "testing"} or os.environ.get("RENDER") == "true"

    @property
    def effective_cors_origins(self) -> str:
        """Return the active CORS origins string.

        Priority:
        1. CORS_ORIGINS environment variable (for Render Dashboard)
        2. cors_origins field (from .env file)
        3. CORS_ORIGIN environment variable (backward compat)
        4. cors_origin field default (localhost for local dev)
        """
        if "CORS_ORIGINS" in os.environ:
            return os.environ["CORS_ORIGINS"]
        if self.cors_origins:
            return self.cors_origins
        if "CORS_ORIGIN" in os.environ:
            return os.environ["CORS_ORIGIN"]
        return self.cors_origin


settings = Settings()
