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

### Directory structure

```
app/
  main.py                        # FastAPI app entry point, lifespan, router registration
  api/                           # Route handlers, grouped by API version
  services/
    <module>/                    # Business logic, one subdirectory per module
    access.py                    # Shared establishment-access checks
  repositories/
    <module>/                    # DB access, one subdirectory per module
  models/
    <module>/                    # SQLAlchemy ORM models
  schemas/
    <module>/                    # Pydantic request and response models
  domain/                        # Enums and plain domain types shared by the layers
  core/
    interfaces/                  # Ports: unit of work, LLM client, object storage
    dependencies.py              # FastAPI dependencies (auth, actors)
    security.py                  # Password hashing and JWT handling
    rate_limit.py                # Rate limiting dependencies
    openapi.py                   # OpenAPI customization
  config/
    settings.py                  # Settings loaded from environment / .env
    logging.py, telemetry.py     # Observability configuration
    log_masking/                 # Masking of sensitive data in logs
  db/
    database.py                  # Async SQLAlchemy engine and session factory
    unit_of_work.py              # Unit of work used by the services
  exceptions/                    # Domain exceptions and their HTTP handlers
  reference_data/                # Reference datasets (CSV, WHO tables) and seeding helpers
  templates/, static/            # Email and PDF report templates and assets
  utils/                         # Small shared helpers
alembic/
  versions/                      # Migration files
tests/
  unit/, integration/, load/     # See docs/commands.md
```

### Layer responsibilities

**`api/`**: HTTP layer only. Validates input, calls services, returns responses. No business logic.

**`services/<module>/`**: Business logic and domain rules for each module. Orchestrates repositories and external calls (LLMs, storage). This is the entry point for the API layer.

**`repositories/<module>/`**: All DB queries live here. No business logic — only data access.

**`models/<module>/`**: SQLAlchemy ORM models. Represent DB tables.

**`schemas/<module>/`**: Pydantic models that define the request and response bodies.

**`domain/`**: Enums and plain domain types (roles, statuses, units) used across layers.

**`core/`**: Cross-cutting infrastructure: the ports that services depend on (`core/interfaces/`), FastAPI dependencies, security and rate limiting.

**`db/`**: Engine, session factory and unit of work. Used by the repositories, the services through the unit of work, and Alembic.

**`config/`**: Application settings (`settings.py`) and observability configuration.

### Module summary

The platform's product modules are implemented by these code modules (one folder per layer each):

| Product module | Code modules | Description |
|---|---|---|
| Auth | `auth`, `establishments` | Users, roles, per-establishment permissions and requests |
| `talla_y_peso` | `subjects`, `measurements` | Subjects and height/weight registration with georeferencing |
| `encuesta_alimentaria` | `surveys` | Configurable surveys, FAO FIES |
| `nutrir` | `food_catalog`, `food_intakes`, `food_outflows`, `food_stock`, `recipes` | Food catalog and stock movements, AI-assisted recipe proposals |
| `dashboard` | analytics routes and services, establishment dashboard | Cross-module analytics for technical profiles |
| Reports and alerts | `nutrition_reports`, `notifications` | Monthly nutrition report PDF and push notifications |

## Data storage

- **PostgreSQL**: primary database for all structured data.
- **Redis**: counters for authentication rate limiting. It holds no other data, and losing it degrades the limits to in-memory counting rather than stopping the service.
- **Alembic**: handles all schema migrations. Never modify the DB schema manually.
- **External storage** (Cloudflare R2, S3-compatible): stores binary files, such as receipt photos (see [ADR-0015](adr/0015-receipt-photo-storage.md)). Services reach it through the `IObjectStorage` port.

## External integrations

| Integration | Used by |
|---|---|
| OpenRouter structured/vision completions | Receipt extraction, recipe selection and writing, and report text |
| Cloudflare R2 (object storage) | Receipt photos |

All external API calls are orchestrated by the services layer. Credentials are never exposed to clients.

The structured LLM adapter is created lazily and shared within one application.
Application lifespan closes its pooled HTTP transport. Missing AI configuration
does not prevent startup or non-inference operations. Select workload models
through environment configuration. Hosting-provider restriction is optional;
request price caps remain zero.

Services call centralized establishment-access helpers explicitly before scoped
work. Routes parse and delegate, and do not duplicate those permission rules.

## Deployment

Containerized with Docker and deployed on Railway (`railway.toml`). A deployment goes live only once `/ready` answers, which requires reaching the database.

The container starts only Uvicorn. Migrations and the superadmin and food catalog seeds run before each deployment through the Railway Pre-Deploy Command, `sh scripts/pre_deploy.sh`. With Docker Compose, the one-shot `migrate` service does the same. See [Docker in docs/commands.md](commands.md#docker).

CI publishes the image to GitHub Container Registry from `develop` and `main`.
