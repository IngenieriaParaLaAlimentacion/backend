# Backend

[![en](https://img.shields.io/badge/lang-en-red.svg)](README.en.md)
[![codecov](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend/graph/badge.svg?token=IJ7UM97UZI)](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)

API REST del proyecto **Ingeniería para la Alimentación**, desarrollada con FastAPI, SQLAlchemy (async) y asyncpg sobre Python 3.11+.

---

## Requisitos previos

| Herramienta | Versión mínima |
|-------------|---------------|
| Python      | 3.11          |
| Poetry      | 2.0           |

> Se recomienda instalar Poetry con `pipx install poetry`.

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/IngenieriaParaLaAlimentacion/backend.git

# 2. Instalar dependencias (incluyendo dev)
poetry install

# 3. Instalar hooks de pre-commit
poetry run pre-commit install
```

---

## Variables de entorno

Crear un archivo `.env` en la raíz del directorio `backend/` basándose en el `.env.example`.

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

Los tests de integración usan **Testcontainers** para levantar una base de datos real de forma efímera. 

```bash
# Correr todos los tests
poetry run pytest

# Con reporte de cobertura
poetry run pytest --cov=app --cov-report=term-missing

# Correr un archivo o test específico
poetry run pytest tests/test_ejemplo.py::test_funcion
```

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

---


## Licencia

Proyecto académico — **grupo-193**.
