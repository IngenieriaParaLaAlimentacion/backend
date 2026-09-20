import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.host == "0.0.0.0"
    assert s.port == 8080
    assert s.environment == "development"
    assert str(s.log_level) == "INFO"
    assert s.service_name == "backend"

    assert s.database_host == "localhost"
    assert s.database_name == "db"
    assert s.database_port == 5432
    assert s.database_user == "admin"
    assert s.database_password == "password"

    assert s.jwt_secret_field_worker == "secret_field_worker"
    assert s.jwt_secret_admin == "secret_admin"
    assert s.jwt_secret_analyst == "secret_analyst"
    assert s.jwt_algorithm == "HS256"
    assert s.access_token_expire_minutes == 15
    assert s.refresh_token_expire_days == 7


def test_settings_invalid_port():
    with pytest.raises(ValidationError):
        Settings(port="notanint")


def test_build_database_url_from_parts():
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://admin:password@localhost:5432/db"


def test_build_database_url_normalizes_shorthand_postgres_scheme():
    s = Settings(_env_file=None, database_url="postgres://user:pw@host:5432/mydb")
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_build_database_url_normalizes_standard_postgresql_scheme():
    s = Settings(_env_file=None, database_url="postgresql://user:pw@host:5432/mydb")
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_fcm_credentials_are_complete_only_when_every_field_is_present():
    assert Settings(_env_file=None).has_fcm_credentials is False
    assert (
        Settings(_env_file=None, fcm_project_id="project").has_fcm_credentials is False
    )
    settings = Settings(
        _env_file=None,
        fcm_project_id="project",
        fcm_client_email="sender@example.test",
        fcm_private_key="key",
    )
    assert settings.has_fcm_credentials is True
