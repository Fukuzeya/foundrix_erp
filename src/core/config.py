"""Application configuration loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Foundrix ERP platform.

    All values are loaded from environment variables or a `.env` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://foundrix:foundrix@localhost:5432/foundrix"

    # Security
    SECRET_KEY: str = "change-me-to-a-random-64-char-string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # File Storage
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_DIR: str = "storage"

    # Environment
    ENVIRONMENT: str = "development"
    PUBLIC_SCHEMA: str = "public"

    @property
    def is_production(self) -> bool:
        """Return True if running in production."""
        return self.ENVIRONMENT == "production"


settings = Settings()
