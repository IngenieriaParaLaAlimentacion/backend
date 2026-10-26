import json
import os

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


@pytest.fixture(autouse=True)
def clear_ai_environment(monkeypatch):
    for key in os.environ:
        if key.startswith("OPENROUTER_") or key in {
            "RECEIPT_GENERATION_TIMEOUT_SECONDS",
            "RECIPE_GENERATION_TIMEOUT_SECONDS",
        }:
            monkeypatch.delenv(key)


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


def test_openrouter_defaults_disable_inference_without_breaking_settings():
    config = Settings(_env_file=None)
    assert config.openrouter_api_key is None
    assert config.openrouter_receipt_models == []
    assert config.openrouter_recipe_models == []
    assert config.openrouter_allowed_providers == []


@pytest.mark.parametrize(
    "model", ["google/gemini-paid", "openrouter/free", "x/y:free "]
)
def test_paid_or_implicit_model_selection_is_rejected(model):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openrouter_receipt_models=[model])


def test_openrouter_key_is_secret_and_blank_is_unset():
    assert Settings(_env_file=None, openrouter_api_key="").openrouter_api_key is None
    config = Settings(_env_file=None, openrouter_api_key="test-secret")
    assert "test-secret" not in repr(config)
    assert config.openrouter_api_key.get_secret_value() == "test-secret"


@pytest.mark.parametrize(
    "field", ["openrouter_receipt_models", "openrouter_recipe_models"]
)
@pytest.mark.parametrize(
    "models",
    [
        ["x/y:free", "x/y:free"],
        ["x/a:free", "x/b:free", "x/c:free"],
    ],
)
def test_unreachable_or_duplicate_model_chain_is_rejected(field, models):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: models})


@pytest.mark.parametrize("providers", [[""], [" host"], ["host "], ["host", "host"]])
def test_unauditable_provider_ids_are_rejected(providers):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openrouter_allowed_providers=providers)


def test_model_and_provider_environment_uses_json_arrays(monkeypatch):
    monkeypatch.setenv("OPENROUTER_RECEIPT_MODELS", json.dumps(["x/vision:free"]))
    monkeypatch.setenv("OPENROUTER_RECIPE_MODELS", json.dumps(["x/text:free"]))
    monkeypatch.setenv("OPENROUTER_ALLOWED_PROVIDERS", json.dumps(["host"]))
    config = Settings(_env_file=None)
    assert config.openrouter_receipt_models == ["x/vision:free"]
    assert config.openrouter_recipe_models == ["x/text:free"]
    assert config.openrouter_allowed_providers == ["host"]


@pytest.mark.parametrize(
    ("field", "minimum", "maximum"),
    [
        ("openrouter_max_attempts", 1, 2),
        ("openrouter_request_timeout_seconds", 0.1, 25),
        ("openrouter_completion_timeout_seconds", 0.1, 40),
        ("openrouter_retry_backoff_max_seconds", 0, 2),
        ("receipt_generation_timeout_seconds", 0.1, 60),
        ("recipe_generation_timeout_seconds", 0.1, 240),
        ("openrouter_max_output_tokens", 256, 65536),
    ],
)
def test_inference_limits_accept_boundaries_and_reject_outside(field, minimum, maximum):
    assert getattr(Settings(_env_file=None, **{field: minimum}), field) == minimum
    assert getattr(Settings(_env_file=None, **{field: maximum}), field) == maximum
    for invalid in [-1, maximum + 1]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: invalid})
    if minimum > 0:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: 0})
