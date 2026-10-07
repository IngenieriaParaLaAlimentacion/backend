import enum
from typing import Optional

from limits import parse as parse_limit
from pydantic import AnyUrl, EmailStr, Field, field_validator, model_validator
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

    # Origin of the backoffice web app. Every emailed link is built on it
    # (verify email, reset password, invite). The default is the local
    # backoffice; each deployed environment sets its own https origin.
    backoffice_deeplink_base: AnyUrl = "http://localhost:3001"

    password_recovery_path: str = "/reset-password"
    email_verification_path: str = "/verify-email"
    invite_path: str = "/invite"

    # Receipt upload
    receipt_image_max_bytes: int = 10 * 1024 * 1024  # 10 MiB
    receipt_image_allowed_types: set[str] = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    receipt_food_match_min_word_similarity: float = 0.5
    receipt_food_match_min_similarity: float = 0.22

    # Object storage (Cloudflare R2, S3-compatible).
    storage_endpoint_url: Optional[str] = None
    storage_bucket: Optional[str] = None
    storage_access_key_id: Optional[str] = None
    storage_secret_access_key: Optional[str] = None
    storage_region: str = "auto"

    # LLM
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.6-flash"
    # Total attempts (first call + retries)
    gemini_max_attempts: int = Field(default=3, ge=1)
    gemini_retry_backoff_initial_seconds: float = 1
    gemini_retry_backoff_max_seconds: float = 8
    # Per-request HTTP timeout, so a stalled connection fails fast instead of
    # hanging forever and never reaching the retry/fallback logic.
    gemini_request_timeout_seconds: float = 30
    # Secondary model tried after the primary exhausts its attempts on a
    # retryable failure. Unset disables the fallback.
    gemini_fallback_model: Optional[str] = None
    gemini_fallback_max_attempts: int = Field(default=2, ge=1)

    # Rate limiting - each limit is "<count>/<period>", e.g. "5/minute".
    rate_limit_redis_url: str = "redis://localhost:6379/0"
    rate_limit_require_x_real_ip: bool = False
    rate_limit_redis_connect_timeout_seconds: float = 0.2
    rate_limit_redis_socket_timeout_seconds: float = 0.2
    rate_limit_login_email: str = "5/minute"
    rate_limit_login_ip: str = "20/minute"
    rate_limit_mail_sending_email: str = "3/hour"
    rate_limit_mail_sending_ip: str = "10/hour"
    rate_limit_token_ip: str = "20/minute"
    rate_limit_register_ip: str = "5/hour"

    # Stale-establishment notifications
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

    @field_validator(
        "rate_limit_login_email",
        "rate_limit_login_ip",
        "rate_limit_mail_sending_email",
        "rate_limit_mail_sending_ip",
        "rate_limit_token_ip",
        "rate_limit_register_ip",
    )
    @classmethod
    def validate_rate_limit(cls, value: str) -> str:
        """Reject a rate limit that is not written as ``<count>/<period>``."""
        # The limit is otherwise only parsed on the first request that uses it,
        # so a typo would let the service start with the endpoint unprotected.
        try:
            parse_limit(value)
        except ValueError as exc:
            raise ValueError(f"invalid rate limit {value!r}: {exc}") from exc
        return value

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
