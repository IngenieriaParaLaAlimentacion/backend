# Architecture

## System overview

The platform is composed of three independent clients and a centralized backend:

- **Mobile app**: used in the field by field workers and health promoters.
- **Backoffice web**: analytics dashboard for nutritionists, doctors, and program coordinators.
- **Backend**: single source of truth. Centralizes all business logic, LLM orchestration, and data access.

Clients never call external services directly. All orchestration goes through the backend.

## Backend architecture

The backend is a **modular monolith**. There are no microservices or API gateway.

Layering is horizontal (one set of directories for the whole app). Module boundaries are enforced inside each layer folder, where each functional module has its own subdirectory.

> **Note**: the exact internal structure of each layer is not fully settled and may evolve. The pattern below is the agreed convention to follow as modules are built out.

### Directory structure

```
app/
  main.py                        # FastAPI app entry point, router registration
  core/
    config.py                    # Settings loaded from environment / .env
  db/
    database.py                  # Async SQLAlchemy engine and session factory
  models/
    module1/
    module2/
    ...
  repositories/
    module1/
    module2/
    ...
  services/
    module1/
    module2/
    ...
  api/
    module1/
    module2/
    ...
alembic/
  versions/                      # Migration files
```

### Layer responsibilities

**`api/<module>/`**: HTTP layer only. Validates input, calls services, returns responses. No business logic.

**`services/<module>/`**: Business logic and domain rules for each module. Orchestrates repositories and external calls (LLMs, storage). This is the entry point for the API layer.

**`repositories/<module>/`**: All DB queries live here. No business logic — only data access.

**`models/<module>/`**: SQLAlchemy ORM models. Represent DB tables and domain models.

**`db/`**: Engine and session factory. Used only by repositories and Alembic.

**`core/`**: Application settings only (`config.py`). No business logic.

### Module summary

| Module | Description |
|---|---|
| `auth` | Users, roles, per-establishment permissions |
| `talla_y_peso` | Height/weight registration with georeferencing (Module 1) |
| `encuesta_alimentaria` | Configurable surveys, FAO FIES (Module 2) |
| `valores_de_hierro` | Blood hemoglobin recording, WHO alerts (Module 3) |
| `nutrir` | AI-assisted meal planning (Module 4) |
| `dashboard` | Cross-module analytics for technical profiles |

## Data storage

- **PostgreSQL**: primary database for all structured data.
- **Redis**: counters for authentication rate limiting. It holds no other data, and losing it degrades the limits to in-memory counting rather than stopping the service.
- **Alembic**: handles all schema migrations. Never modify the DB schema manually.
- **External storage** (S3-compatible, TBD): stores binary files — informed consent PDFs and images uploaded via `nutrir` and `valores_de_hierro`.

## External integrations

| Integration | Used by |
|---|---|
| LLM API (provider TBD) | `nutrir` (meal planning agent), `dashboard` (natural language analysis) |
| Vision / Speech-to-text API | `nutrir` (ingredient input via image or voice) |
| Storage service | `nutrir`, `valores_de_hierro` |

All external API calls are orchestrated by the services layer. Credentials are never exposed to clients.

## Deployment

Containerized with Docker. Target infrastructure TBD.

Migrations run automatically on startup via the Docker entrypoint:
```bash
alembic upgrade head
```
