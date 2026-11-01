# Load-test runner: k6 plus the backend's Python dependencies, which the seed and
# the cleanup need to reach the target's database.

FROM grafana/k6:2.2.0 AS k6

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN poetry install --without dev --no-root

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=k6 /usr/bin/k6 /usr/bin/k6
COPY --from=builder /app/.venv .venv
# The dependencies change less often than the code, so they come first and stay cached.
COPY app app
COPY tests/__init__.py tests/__init__.py
COPY tests/load tests/load

ENTRYPOINT ["sh", "tests/load/run.sh"]
CMD ["all"]
