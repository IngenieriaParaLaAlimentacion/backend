# Alembic Migrations

## Common commands

**Generate a migration after changing a model:**
```bash
poetry run alembic revision --autogenerate -m "describe what changed"
```

**Apply all pending migrations:**
```bash
poetry run alembic upgrade head
```

**Undo the last migration:**
```bash
poetry run alembic downgrade -1
```

**Check current DB version:**
```bash
alembic current
```

**List all migrations:**
```bash
alembic history
```

## Rules

- Always review the generated file in `versions/` before applying it
- Never edit a migration that has already been applied
- Always commit migration files