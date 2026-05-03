# Ingeniería para la Alimentación — Backend

[![en](https://img.shields.io/badge/lang-en-red.svg)](README.en.md)
[![codecov](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend/graph/badge.svg?token=mR49XH6LdK)](https://app.codecov.io/gh/IngenieriaParaLaAlimentacion/backend)


API REST del proyecto **Ingeniería para la Alimentación**, desarrollada con FastAPI y SQLAlchemy sobre Python 3.11+.

---

## Tabla de contenidos

- [Ingeniería para la Alimentación — Backend](#ingeniería-para-la-alimentación--backend)
  - [Tabla de contenidos](#tabla-de-contenidos)
  - [Requisitos previos](#requisitos-previos)
  - [Instalación](#instalación)
  - [Variables de entorno](#variables-de-entorno)
  - [Ejecución](#ejecución)
  - [Tests](#tests)
  - [Linting y formato](#linting-y-formato)
  - [Licencia](#licencia)

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
# Servidor de desarrollo con hot-reload
poetry run uvicorn app.main:app --reload

# O bien, activando el virtualenv primero
poetry shell
uvicorn app.main:app --reload

# Usando docker compose
docker compose up --build
```

La API queda disponible en `http://localhost:8000`.  
La documentación interactiva (Swagger UI) se encuentra en `http://localhost:8000/docs`.

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


## Licencia

Proyecto académico — **grupo-193**.