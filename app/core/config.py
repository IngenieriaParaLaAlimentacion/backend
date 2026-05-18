import enum
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(str, enum.Enum):
    """Possible log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    environment: str = "development"
    log_level: str = LogLevel.INFO
    service_name: str = "backend"

    # Database - DATABASE_URL is not set
    database_host: str = "localhost"
    database_name: str = "db"
    database_port: int = 5432
    database_user: str = "admin"
    database_password: str = "password"

    # Database - DATABASE_URL is set
    database_url: Optional[str] = None

    # JWT
    jwt_secret_manager: str = "secret_manager"
    jwt_secret_admin: str = "secret_admin"
    jwt_secret_professional: str = "secret_professional"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        """Resolve the final async-compatible database URL.

        SQLAlchemy requires the scheme 'postgresql+asyncpg://' to use the
        asyncpg driver. This validator ensures the correct scheme regardless
        of how the URL is provided.
        """
        if self.database_url:
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql+asyncpg://", 1
            ).replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            self.database_url = (
                f"postgresql+asyncpg://{self.database_user}:{self.database_password}"
                f"@{self.database_host}:{self.database_port}/{self.database_name}"
            )
        return self

    @property
    def database_url_sync(self) -> str:
        """Sync database URL for Alembic migrations.

        Alembic runs synchronously and requires psycopg2 instead of asyncpg.
        """
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


settings = Settings()
