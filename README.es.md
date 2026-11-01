# Ingeniería en Alimentación · Backend

[![en](https://img.shields.io/badge/lang-en-red.svg?logo=googletranslate&logoColor=white)](README.md)
[![codecov](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend/graph/badge.svg?token=IJ7UM97UZI)](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](pyproject.toml)

API REST del proyecto **Ingeniería para la Alimentación**, desarrollada con FastAPI, SQLAlchemy (async) y asyncpg sobre Python 3.11+.

---

## Documentación

> La documentación técnica está en inglés.

- [Comandos](docs/commands.md): configuración inicial, desarrollo, migraciones, datos de referencia E2E y carga de datos.
- [Arquitectura](docs/architecture.md).
- [Autenticación y autorización](docs/auth.md).
- [Convenciones de código](docs/conventions.md).
- [Convenciones de la API](docs/api.md).
- [Catálogo de errores](docs/errors.md).
- [Decisiones de arquitectura (ADR)](docs/adr/).
- [Pruebas de carga](tests/load/README.md).
- [Notificaciones push de establecimientos sin actualizar: Firebase y Railway](docs/stale-establishment-push-railway-setup.md).
- [Guía de contribución](CONTRIBUTING.md).
- [Convenciones de desarrollo para agentes](CLAUDE.md).

---

## Requisitos previos

| Herramienta | Versión mínima | Notas |
|-------------|----------------|-------|
| Python | 3.11 | |
| Poetry | 2.0 | Se recomienda instalarlo con `pipx install poetry` |
| Docker | | Requerido para los tests de integración (Testcontainers) y para `docker compose` |
| PostgreSQL | | Solo para desarrollo local sin Docker |
| Redis | | Para el límite de tasa. Sin Docker: `docker compose up redis` |
| Pango y HarfBuzz | | Bibliotecas nativas de WeasyPrint. La app no arranca sin ellas |

Para instalar Pango y HarfBuzz en macOS: `brew install pango`. En Debian o Ubuntu, los paquetes están en [docs/commands.md](docs/commands.md#prerequisites).

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/IngenieriaParaLaAlimentacion/backend.git
cd backend

# 2. Instalar dependencias (incluyendo dev)
poetry install

# 3. Instalar hooks de pre-commit
poetry run pre-commit install

# 4. Crear el archivo de variables de entorno
cp .env.example .env
```

---

## Variables de entorno

Editá el `.env` creado a partir de `.env.example` y cambiá los valores que difieran de los predeterminados.

> El proyecto usa `pydantic-settings` para cargar y validar las variables de entorno automáticamente.

---

## Ejecución

```bash
# Con PostgreSQL local y DATABASE_HOST=localhost en .env:
poetry run alembic upgrade head
poetry run python seed_superadmin.py
poetry run python seed_food_catalog.py

# Servidor de desarrollo con hot-reload
poetry run uvicorn app.main:app --reload

# O bien, activando el virtualenv primero
poetry shell
uvicorn app.main:app --reload

# Usando docker compose
docker compose up --build
```

La API queda disponible en `http://localhost:8080`.
La documentación interactiva (Swagger UI) se encuentra en `http://localhost:8080/docs`.

---

## Tests

Los tests de integración usan **Testcontainers** para levantar una base de datos real de forma efímera, por lo que Docker debe estar en ejecución.

```bash
# Correr todos los tests
poetry run pytest

# Solo los unitarios o solo los de integración
poetry run pytest tests/unit
poetry run pytest tests/integration

# Con reporte de cobertura
poetry run pytest --cov=app --cov-report=term-missing

# Correr un archivo o test específico
poetry run pytest tests/unit/test_dates.py::test_completed_months_between
```

Las pruebas de carga (k6) están en `tests/load/` y se describen en [su README](tests/load/README.md). Los datos de referencia para las pruebas E2E se explican en [docs/commands.md](docs/commands.md#e2e-reference-data).

---

## Linting y formato

El proyecto usa **Ruff** para linting (reglas `E`, `F`, `I`) y formateo (comillas dobles, largo de línea 88).

```bash
# Verificar errores de linting
poetry run ruff check .

# Corregir automáticamente lo que se pueda
poetry run ruff check . --fix

# Formatear el código
poetry run ruff format .
```

Los hooks de **pre-commit** corren estas verificaciones automáticamente antes de cada commit. Para ejecutarlos manualmente sobre todos los archivos:

```bash
poetry run pre-commit run --all-files
```

---

## Migraciones de base de datos

`docker compose up --build` ejecuta primero el servicio `migrate` y después inicia el backend. Reiniciar el backend no vuelve a migrar ni sembrar datos.

En Railway, configurar el **Pre-Deploy Command** del servicio backend en los ambientes de test y producción como `sh scripts/pre_deploy.sh`. Este comando aplica las migraciones y ejecuta los seeds de superadmin y catálogo de alimentos; si falla, el nuevo deploy no arranca. El `Dockerfile` inicia solo Uvicorn.

Para ejecutar el paso manualmente:

```bash
poetry run alembic upgrade head && poetry run python seed_superadmin.py && poetry run python seed_food_catalog.py
```

Para crear o revertir migraciones, consultá [docs/commands.md](docs/commands.md#database-and-migrations).

---

## Contribuir

Leé la [guía de contribución](CONTRIBUTING.md) antes de abrir un PR: ramas, commits y revisión.

---

## Licencia

Proyecto académico — **grupo-193**.
