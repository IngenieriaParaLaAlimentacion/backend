import enum
from datetime import datetime
from typing import Optional

from pydantic import AnyUrl, EmailStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.user import UserRole


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
    jwt_secret_field_worker: str = "secret_field_worker"
    jwt_secret_admin: str = "secret_admin"
    jwt_secret_analyst: str = "secret_analyst"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # superadmin
    seed_admin_email: EmailStr = "admin@dashboard.com"
    seed_admin_password: str = "Admin123!"

    # Email verification
    email_verification_token_expire_minutes: int = 1440  # 24 hours

    # Password recovery
    password_recovery_token_expire_minutes: int = 30

    # SMTP
    smtp_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = False
    smtp_sender_email: EmailStr = "no-reply@tpp.com"

    # Base URL used by every frontend deeplink (all links target the backoffice).
    backoffice_deeplink_base: AnyUrl = "http://i_need_deeplink.com"

    password_recovery_path: str = "/reset-password"
    email_verification_path: str = "/verify-email"
    invite_path: str = "/invite"

    # Stale-establishment notifications
    stale_notifications_feature_activated_at: datetime | None = None
    stale_notifications_cron_secret: str | None = None
    fcm_project_id: str | None = None
    fcm_client_email: str | None = None
    fcm_private_key: str | None = None

    @property
    def has_fcm_credentials(self) -> bool:
        """Return whether every FCM service-account field is present."""
        return all((self.fcm_project_id, self.fcm_client_email, self.fcm_private_key))

    def _build_deeplink(self, base: str | AnyUrl, path: str) -> str:
        base = str(base).rstrip("/")
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base}{path}"

    @property
    def backoffice_password_reset_deeplink(self) -> str:
        """Derived password reset deeplink URL from the backoffice base URL."""
        return self._build_deeplink(
            self.backoffice_deeplink_base, self.password_recovery_path
        )

    @property
    def email_verification_deeplink_url(self) -> str:
        """Derived email verification deeplink URL from the backoffice base URL."""
        return self._build_deeplink(
            self.backoffice_deeplink_base, self.email_verification_path
        )

    def invite_deeplink_url(self, role: UserRole) -> str:
        """Derived invitation deeplink URL for a backoffice role."""
        return self._build_deeplink(
            self.backoffice_deeplink_base, f"{self.invite_path}/{role}"
        )

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


settings = Settings()
