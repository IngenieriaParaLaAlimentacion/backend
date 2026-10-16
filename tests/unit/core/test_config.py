import pytest
from pydantic import ValidationError

from app.config.settings import Settings


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


@pytest.mark.parametrize("value", ["5/minuto", "five/minute", "5", "", "5/"])
def test_a_malformed_rate_limit_fails_at_startup(value):
    with pytest.raises(ValidationError, match="rate_limit_login_ip"):
        Settings(_env_file=None, rate_limit_login_ip=value)


@pytest.mark.parametrize("value", ["5/minute", "3/hour", "20 per minute"])
def test_a_well_formed_rate_limit_is_accepted(value):
    assert Settings(_env_file=None, rate_limit_token_ip=value).rate_limit_token_ip


@pytest.mark.parametrize("value", ["", None])
def test_an_empty_service_token_counts_as_unset(value):
    assert (
        Settings(_env_file=None, internal_service_token=value).internal_service_token
        is None
    )
