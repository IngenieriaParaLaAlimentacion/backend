import importlib
import os
import sys
from urllib.parse import urlparse

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from alembic import command

os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def app(postgres_url):
    parsed = urlparse(postgres_url.replace("postgresql+asyncpg://", "postgresql://"))
    os.environ["DATABASE_HOST"] = parsed.hostname
    os.environ["DATABASE_PORT"] = str(parsed.port)
    os.environ["DATABASE_NAME"] = parsed.path.lstrip("/")
    os.environ["DATABASE_USER"] = parsed.username
    os.environ["DATABASE_PASSWORD"] = parsed.password
    os.environ["JWT_SECRET"] = "test-secret"

    for module_name in [
        name for name in sys.modules if name == "app" or name.startswith("app.")
    ]:
        sys.modules.pop(module_name)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_cfg, "head")

    module = importlib.import_module("app.main")
    return module.app


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client
