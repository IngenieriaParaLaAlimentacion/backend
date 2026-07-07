# Survey Authoring (encuesta_alimentaria) Implementation Plan

## Overview

Implement backoffice **survey authoring** for Module 2 (`encuesta_alimentaria`):
administrators and analysts create and configure surveys — FIES or custom — scoped
generically or to specific establishments, with 1–30 questions of five response types,
ordered, optional/required, with choice options. Surveys can be duplicated, activated /
deactivated, listed, and deleted.

This is a **greenfield module** built on the established flat layered architecture
(`models` → `domain` → `schemas` → `repositories` → `services` → `api`), the
`UnitOfWork` pattern, RFC 7807 `problem+json` exceptions, role-based FastAPI
dependencies, Alembic migrations, and pytest + Testcontainers. The `talla_y_peso`
(measurement) vertical slice is the reference to model after.

Covers acceptance criteria **CA1–CA9**, with two deliberate deviations recorded in
[ADR-0002](../adr/0002-fies-as-template-no-survey-type.md).

## Current State Analysis

- The `encuesta_alimentaria` / survey module **does not exist** — no models, domain,
  schemas, repository, service, routes, or tests.
- The repo uses a **flat** layout (one file per concept per layer), not per-module
  subdirectories, despite `CLAUDE.md`/`docs/architecture.md` describing subdirs. New
  files follow the existing flat convention (e.g. `app/models/measurement.py`,
  `app/repositories/measurement_repository.py`).
- Reference patterns already in place:
  - `app/models/measurement.py`, `app/models/measurement_alert.py:24` — `SAEnum(..., values_callable=lambda x: [e.value for e in x])` for enum columns; `ForeignKey(..., ondelete="CASCADE")`; `server_default=func.now()`.
  - `app/domain/measurement.py` — dataclasses with `from_db` classmethods, `StrEnum` sort orders, `*ListingParams` dataclass with `__post_init__` trimming, ref dataclasses (`SubjectRefDomain`, etc.).
  - `app/repositories/measurement_repository.py:150` — SAVEPOINT-wrapped insert (`async with self.db.begin_nested()`) translating `IntegrityError` → `UniqueConstraintError`; `_SORT_CLAUSES` dict; `execute_paginated` usage.
  - `app/utils/db.py:13` — `execute_paginated(db, base_query, count_query, order_by, limit, offset)`; `escape_like` for search.
  - `app/services/measurement_service.py:44` — `_check_establishment_access` permission-gate pattern raising `ForbiddenError`; `_get_establishment_or_raise`.
  - `app/schemas/measurement_schema.py` — `ConfigDict(from_attributes=True)`, `Field(...)` constraints, `field_validator`.
  - `app/schemas/pagination.py` (`PaginatedResponse[T]`) + `app/domain/pagination.py` (`PaginatedResult.build`).
  - `app/api/v1/measurements.py` — router with `prefix`, `require_some(...)` deps, `responses={...}` OpenAPI docs; `app/api/v1/params.py` — `MeasurementListingQuery` dataclass with `validate()` + `to_domain()`.
  - `app/core/dependencies.py:63` — `get_<x>_service()` async generator yielding a service over a fresh `UnitOfWork`; `require_some(*roles)`, `require_any`.
  - `app/core/interfaces/unit_of_work.py` + `app/db/unit_of_work.py` — repos declared on `IUnitOfWork` and instantiated in `UnitOfWork.__aenter__`.
  - `app/exceptions/domain_exceptions.py` — `NotFoundError`, `AlreadyExistsError`, `BadRequestError`, `ForbiddenError`, `UniqueConstraintError` bases; `app/exceptions/exception_handlers.py` maps them to status codes (`AlreadyExistsError` → 409).
  - `app/models/__init__.py` — every model is imported/re-exported here (Alembic autogenerate + mapper registration depend on it).
  - `alembic/versions/a4f2c8e1d3b7_*.py` — migration style: `op.create_table`, `sa.Enum(..., name=...)`, `ondelete="CASCADE"`, index creation, and enum drop in `downgrade`.

### Key Discoveries

- **No offline-first here.** The backoffice is online — do **not** replicate the
  client-generated-UUID idempotency machinery used for measurements/subjects. Server
  assigns ids. (See [ADR-0001](../adr/0001-declarative-whole-survey-authoring-api.md).)
- **Auth middleware is not implemented** — per-role checks are done via FastAPI deps
  (`require_some`) at the route, and ownership/permission checks live in the service
  (like `MeasurementService._check_establishment_access`). This plan follows that
  existing reality.
- **Enum values** must use `values_callable` so the DB stores the lowercase string values
  (`generic`, `single_choice`, …), matching `measurement_alert.py`.

## Desired End State

A `/surveys` API under `app/api/v1/surveys.py` (tag "Surveys V1"), registered in
`app/api/v1/router.py`, exposing create / read / list / reconcile-update / duplicate /
delete / activate-toggle / FIES-template endpoints, backed by four new tables. All
CA1–CA9 behaviors verified by unit + integration tests at ≥80% coverage.

## What We're NOT Doing

- **No response collection**: no answering endpoint, no `survey_responses` /
  `survey_answers` tables, no mobile flow. `is_required`, `scope`, and `is_active` are
  **stored but not consumed** — they will be read by the future answering ticket.
- **No offline-first / client-generated ids** for authoring.
- **No CA8 structural taxonomy**: the edit-lock is a stub (see Phase 5). Only CA7 is fully
  enforced now.
- **No FIES scoring / dashboard analytics**, and **no persistent survey `type`** or
  per-question origin marker (ADR-0002).
- **No extra per-type question config** (numeric min/max, date bounds, per-question text
  limits beyond the field length cap).
- **No reorder endpoint** — ordering is array position on `PUT` (ADR-0001).

## Implementation Approach

Build bottom-up along layer boundaries: domain enums/dataclasses → ORM models →
migration → exceptions → aggregate repository → schemas → service → API + app wiring →
FIES template data → tests. The survey + questions + options + establishments form a
single **aggregate** persisted through one `SurveyRepository`; the declarative `PUT`
reconciles the aggregate in one transaction.

### Data model (4 tables, one migration)

| Table | Columns |
|---|---|
| `surveys` | `id` (UUID PK), `name` (String, unique via `lower(name)` functional index; trimmed; 1–120), `description` (String, nullable, ≤1000), `scope` (enum `surveyscope`: `generic`\|`targeted`), `created_by_id` (FK `users.id`, `ondelete=RESTRICT`), `is_active` (Boolean, NOT NULL, default `true`), `response_count` (Integer, NOT NULL, default `0`, **stub**), `created_at`, `updated_at` |
| `survey_questions` | `id` (UUID PK), `survey_id` (FK `surveys.id`, `ondelete=CASCADE`), `text` (String, ≤500), `response_type` (enum `responsetype`: `text`\|`single_choice`\|`multiple_choice`\|`numeric`\|`date`), `is_required` (Boolean), `position` (Integer) |
| `survey_question_options` | `id` (UUID PK), `question_id` (FK `survey_questions.id`, `ondelete=CASCADE`), `text` (String, ≤200), `position` (Integer) |
| `survey_establishments` | `survey_id` (FK `surveys.id`, CASCADE) + `establishment_id` (FK `establishments.id`, CASCADE), composite PK |

Index also `survey_questions.survey_id` and `survey_question_options.question_id`
(mirroring `ix_measurement_alerts_measurement_id`).

---

## Phase 1: Domain, models, migration

### Overview

Enums, domain dataclasses, ORM models, and the schema migration.

### Changes Required

#### 1. Domain — `app/domain/survey.py`

- `class ResponseType(str, Enum)`: `TEXT`, `SINGLE_CHOICE`, `MULTIPLE_CHOICE`, `NUMERIC`, `DATE` (values `text`, `single_choice`, …).
- `class SurveyScope(str, Enum)`: `GENERIC = "generic"`, `TARGETED = "targeted"`.
- `class SurveySortOrder(StrEnum)`: `NAME_ASC`, `NAME_DESC`, `NEWEST`, `OLDEST`.
- Constants: `MIN_QUESTIONS = 1`, `MAX_QUESTIONS = 30`, `MIN_OPTIONS = 2`, `MAX_OPTIONS = 20`, plus length caps (`NAME_MAX = 120`, `DESCRIPTION_MAX = 1000`, `QUESTION_TEXT_MAX = 500`, `OPTION_TEXT_MAX = 200`) — single source of truth reused by schema + service.
- `CHOICE_TYPES = {ResponseType.SINGLE_CHOICE, ResponseType.MULTIPLE_CHOICE}`.
- Dataclasses with `from_db` (follow `domain/measurement.py`): `OptionDomain`, `QuestionDomain` (with `options: list[OptionDomain]`), `SurveyDomain` (with `questions`, `establishment_ids`, `created_by_id`, `is_active`, `response_count`), `SurveyRefDomain`/list-item, and `SurveyListingParams` dataclass (`search`, `created_by`, `scope`, `is_active`, `sort_order`) with `__post_init__` trimming `search`.

#### 2. Models — `app/models/survey.py`, `survey_question.py`, `survey_question_option.py`, `survey_establishment.py`

Follow `measurement.py` / `measurement_alert.py`:

```python
# app/models/survey.py
class Survey(Base):
    __tablename__ = "surveys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    scope = Column(
        SAEnum(SurveyScope, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    created_by_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_active = Column(Boolean, nullable=False, server_default=sa.true())
    response_count = Column(Integer, nullable=False, server_default="0")  # STUB
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    questions = relationship(
        "SurveyQuestion", back_populates="survey",
        cascade="all, delete-orphan", order_by="SurveyQuestion.position", lazy="selectin",
    )
    establishments = relationship(
        "Establishment", secondary="survey_establishments", lazy="selectin"
    )
```

- `SurveyQuestion` — FK `survey_id` CASCADE; `options` relationship (`cascade="all, delete-orphan"`, `order_by="SurveyQuestionOption.position"`, `lazy="selectin"`); `back_populates="questions"`.
- `SurveyQuestionOption` — FK `question_id` CASCADE; `back_populates="options"`.
- `SurveyEstablishment` — composite PK join table (mirror `user_establishment.py`).
- Register all four in `app/models/__init__.py` (`__all__` + imports) — **required** for Alembic autogenerate and mapper resolution.

#### 3. Migration — `alembic/versions/<rev>_add_survey_tables.py`

- Generate: `poetry run alembic revision --autogenerate -m "add survey tables"`, then hand-verify against `a4f2c8e1d3b7_*.py` style.
- Create the two enums (`surveyscope`, `responsetype`), the four tables, FK `ondelete` rules, and indexes.
- **Functional unique index** (autogenerate will NOT emit this — add manually):
  ```python
  op.create_index(
      "uq_surveys_lower_name", "surveys", [sa.text("lower(name)")], unique=True
  )
  ```
- `downgrade`: drop indexes, drop tables (children first), then `sa.Enum(name="responsetype").drop(op.get_bind())` and `sa.Enum(name="surveyscope").drop(op.get_bind())`.

### Success Criteria

#### Automated Verification
- [x] Lint + format: `poetry run pre-commit run --all-files`
- [ ] Migration applies: `poetry run alembic upgrade head` — **blocked: Docker unavailable**
- [ ] Migration round-trips: `poetry run alembic downgrade -1 && poetry run alembic upgrade head` — **blocked: Docker unavailable**
- [x] Models import cleanly: `poetry run python -c "import app.models"`
- [x] Single alembic head: `poetry run alembic heads` → `b7e3c9a1f2d4 (head)`

#### Manual Verification
- [ ] `\d surveys` shows the `uq_surveys_lower_name` unique functional index and enum columns.
- [ ] Cascade FKs present on `survey_questions`, `survey_question_options`, `survey_establishments`.

---

## Phase 2: Exceptions & repository

### Overview

Domain exceptions and the single aggregate `SurveyRepository`.

### Changes Required

#### 1. Exceptions — `app/exceptions/domain_exceptions.py` + `exception_handlers.py`

- `SurveyNotFoundError(NotFoundError)` → 404 (reuses existing handler).
- Add a **`ConflictError(BaseError)`** base and register a handler mapping it to
  **409** in `exception_handlers.py` (`register_exception_handlers`). Then
  `SurveyLockedError(ConflictError)` → 409 with a distinct RFC 7807 `title`
  ("Survey locked"). Rationale: `AlreadyExistsError` is also 409 but semantically means
  "duplicate", so a separate `ConflictError` keeps the problem `type`/`title` meaningful.
- Reuse `AlreadyExistsError` (name clash → 409), `ForbiddenError` (403),
  `EstablishmentNotFoundError` (404), `UniqueConstraintError` (repo→service translation).

#### 2. Repository — `app/repositories/survey_repository.py`

Single `SurveyRepository(db: AsyncSession)` owning the whole aggregate:

- `get_by_id(id) -> Survey | None` — `selectin` already eager-loads questions→options +
  establishments; return via `self.db.get(Survey, id)`.
- `name_exists(name, exclude_id=None) -> bool` — `select(exists())` on
  `func.lower(Survey.name) == func.lower(name.strip())`, optionally excluding a survey id
  (for rename). Service pre-check for CA2.
- `list(limit, offset, params) -> tuple[list[Survey], int]` — build base/count queries,
  apply `_listing_conditions` (name `ilike` with `escape_like`, `created_by_id`, `scope`,
  `is_active`), `_SORT_CLAUSES` dict, delegate to `execute_paginated`.
- `create(*, name, description, scope, created_by_id, questions, establishment_ids) -> Survey`
  — build the `Survey` with nested `SurveyQuestion` + `SurveyQuestionOption` (positions
  from array index) and `SurveyEstablishment` rows; SAVEPOINT-wrapped flush translating
  `IntegrityError` → `UniqueConstraintError("name", name)` (belt-and-suspenders behind the
  service pre-check, matching `measurement_repository.create`).
- `reconcile(survey, *, name, description, scope, questions, establishment_ids) -> Survey`
  — apply metadata; diff questions/options by id (update known, insert new, delete
  missing); rewrite `position` from array order; replace establishment rows; SAVEPOINT
  flush with the same translation. **Ownership guard**: any supplied question/option id
  not currently belonging to `survey` → raise `SurveyNotFoundError` (or a dedicated
  `BadRequestError`) — decided: reuse a `BadRequestError` subclass
  `InvalidSurveyPayloadError` for "id not part of this survey".
- `duplicate(source, *, new_name, created_by_id) -> Survey` — deep-copy questions/options
  (fresh ids, same order) + description + scope + establishments; `response_count=0`.
- `delete(survey) -> None` — `await self.db.delete(survey)` (ORM cascade handles children).
- `update_active(survey, is_active) -> Survey`.

Register `survey_repo: SurveyRepository` on `IUnitOfWork` and instantiate it in
`UnitOfWork.__aenter__`.

### Success Criteria

#### Automated Verification
- [x] Lint + format: `poetry run pre-commit run --all-files`
- [x] `poetry run python -c "from app.db.unit_of_work import UnitOfWork"`
- [ ] Integration repo tests green (added in Phase 6) — **blocked: Docker unavailable**

---

## Phase 3: Schemas

### Overview

Pydantic request/response schemas in `app/schemas/survey_schema.py`, plus the
`SurveyListingQuery` params dataclass.

### Changes Required

#### 1. `app/schemas/survey_schema.py`

- **Requests**:
  - `OptionInput` — `id: UUID | None = None`, `text: str = Field(min_length=1, max_length=200)`.
  - `QuestionInput` — `id: UUID | None = None`, `text: Field(1..500)`, `response_type: ResponseType`, `is_required: bool`, `options: list[OptionInput] = []`.
  - `SurveyCreateRequest` — `name: Field(1..120)`, `description: str | None = Field(None, max_length=1000)`, `scope: SurveyScope`, `questions: list[QuestionInput]`, `establishment_ids: list[UUID] = []`. Field-level `field_validator` trims name/description/text and rejects blank-after-trim. **Cross-field structural validation** (count 1–30, choice⇒2–20 options, non-choice⇒0 options, duplicate option text, targeted⇒≥1 est / generic⇒0 est) is done in the **service**, not the schema, so it raises domain exceptions with RFC 7807 bodies (schema stays boundary/shape validation). *(Field length/1-item shape can stay in Pydantic; semantic rules in service.)*
  - `SurveyUpdateRequest` — same shape as create **without** `is_active`.
  - `SurveyStatusRequest` — `is_active: bool`.
  - `SurveyDuplicateRequest` — empty body (name is derived server-side) or omit a body entirely.
- **Responses** (`ConfigDict(from_attributes=True)`): `OptionResponse`, `QuestionResponse`, `SurveyResponse` (full config incl. `is_active`, `created_by_id`, ordered questions→options, `establishment_ids`), `SurveyListItem` (id, name, scope, is_active, created_by_id, question_count, created_at).

#### 2. `app/api/v1/params.py`

- `SurveyListingQuery` dataclass mirroring `MeasurementListingQuery`: `search`, `created_by`, `scope`, `is_active`, `sort_order: SurveySortOrder`, with `to_domain() -> SurveyListingParams`.

### Success Criteria
- [x] `poetry run pre-commit run --all-files`
- [x] `poetry run python -c "import app.schemas.survey_schema, app.api.v1.params"`

---

## Phase 4: Service

### Overview

`SurveyService(uow)` — permission gates, validation, reconciliation orchestration,
duplicate-name suffixing, edit-lock stub.

### Changes Required — `app/services/survey_service.py`

- `_assert_can_create(actor)` — role ∈ {admin, analyst, superadmin} (route also enforces).
- `_assert_can_edit(actor, survey)` — owner (`created_by_id == actor.user_id`) **or**
  admin/superadmin; else `ForbiddenError` (mirror `_check_establishment_access`).
- `_assert_editable(survey)` — **stub**: `if survey.response_count > 0: raise SurveyLockedError(...)`.
  ```python
  # TODO(surveys): response collection is out of scope, so response_count is always 0
  # and this never blocks — which satisfies CA7 (no responses => all edits allowed).
  # When the response-collection ticket lands, replace this coarse gate with a
  # per-edit structural-vs-safe taxonomy to enforce CA8:
  #   block: delete question, change response_type, optional->required, remove a
  #          referenced option;  allow: rename, reorder, add optional question.
  ```
  Called at the top of `update` (PUT) and `delete`. **Not** called by the status toggle.
- `_validate_structure(questions, scope, establishment_ids)` — CA5/CA9/scope rules:
  1–30 questions; each choice type has 2–20 non-empty, de-duplicated (case-insensitive,
  trimmed) options; non-choice types carry no options; targeted⇒≥1 establishment (each
  must exist via `uow.establishment_repo.get_by_id` else `EstablishmentNotFoundError`),
  generic⇒0. Raises `BadRequestError` subclasses with clear messages.
- `create(data, actor)` — assert role; name pre-check (`name_exists` → `AlreadyExistsError`);
  validate structure; `uow.survey_repo.create(...)`; `await uow.commit()`; return `SurveyDomain.from_db`.
- `get(id)` — `get_by_id` or `SurveyNotFoundError`.
- `list(page, page_size, params)` — `PaginatedResult.build` over `survey_repo.list`.
- `update(id, data, actor)` — load or 404; `_assert_can_edit`; `_assert_editable`; name
  pre-check with `exclude_id`; validate structure; `survey_repo.reconcile(...)`; commit.
- `duplicate(id, actor)` — load or 404; `_assert_can_create`; compute unique name
  (`"{name} (copy)"`, then `"(copy 2)"`, `"(copy 3)"`… via `name_exists` loop);
  `survey_repo.duplicate(...)`; commit; return full config.
- `delete(id, actor)` — load or 404; `_assert_can_edit`; `_assert_editable`; delete; commit.
- `set_active(id, is_active, actor)` — load or 404; `_assert_can_edit`; **no** `_assert_editable`;
  `survey_repo.update_active`; commit.

### Success Criteria
- [x] `poetry run pre-commit run --all-files`
- [x] Unit tests (Phase 6) green: `poetry run pytest tests/unit/test_survey_service.py` (35 passed)

---

## Phase 5: API, app wiring & FIES template

### Overview

Routes, dependency wiring, and the read-only FIES template.

### Changes Required

#### 1. FIES template — `app/data/fies_template.py`

Module constant returning the canonical FIES structure. Model as **8 `single_choice`
questions**, options **"Sí" / "No"** (positions 0–1), all **`is_required=True`**,
`position` 0–7 in the order below. The template's `name` is left for the user to fill;
its `description` carries the reference-period preamble so each item reads as a
completion of it.

**Reference period / preamble (survey `description`):**
> «Durante los últimos 12 meses, hubo alguna vez en que, por falta de dinero u otros
> recursos:»

**The 8 items (individual referent, 12-month reference period), in FAO order.** The code
constant should keep the FAO short label as a comment on each item for traceability
(labels are **not** persisted — no per-question origin marker, per ADR-0002):

| # | FAO label | Question text (Spanish) |
|---|---|---|
| 1 | WORRIED  | ¿Le preocupó no tener suficientes alimentos para comer? |
| 2 | HEALTHY  | ¿No pudo comer alimentos sanos y nutritivos? |
| 3 | FEWFOODS | ¿Comió poca variedad de alimentos? |
| 4 | SKIPPED  | ¿Tuvo que saltarse una comida? |
| 5 | ATELESS  | ¿Comió menos de lo que pensaba que debía comer? |
| 6 | RANOUT   | ¿Su hogar se quedó sin alimentos? |
| 7 | HUNGRY   | ¿Sintió hambre pero no comió? |
| 8 | WHLDAY   | ¿Dejó de comer durante todo un día? |

Notes:
- FAO publishes the FIES in variants — **individual vs household** referent and
  **12-month vs 30-day** reference period. This template uses the **individual /
  12-month** variant; if the program standardizes on the household or 30-day version,
  adjust the preamble and pronouns accordingly. This is a **content choice**, not a
  blocker — the wording above is drawn from FAO/validated Spanish sources (see the FIES
  references section).
- The "Sí"/"No" dichotomy matches FAO scoring (Sí=1, No=0). FAO field instruments also
  offer a "No sabe / No responde" option; it is intentionally omitted here since the
  survey answering flow (and any FIES scoring) is out of scope — revisit with the
  answering ticket if a don't-know code is required.

#### 2. Dependencies — `app/core/dependencies.py`

- `get_survey_service()` async generator (mirror `get_measurement_service`).
- Reuse `require_some(UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN)` for authoring.

#### 3. Routes — `app/api/v1/surveys.py` (`router = APIRouter(prefix="/surveys")`)

| Method / path | Dep (role) | Notes |
|---|---|---|
| `POST /surveys` | admin/analyst/superadmin | 201; `SurveyResponse` |
| `GET /surveys/{id}` | admin/analyst/superadmin | full config |
| `GET /surveys` | admin/analyst/superadmin | `PaginatedResponse[SurveyListItem]`, `SurveyListingQuery` + page/page_size |
| `PUT /surveys/{id}` | admin/analyst/superadmin | reconcile; service enforces owner/admin + lock |
| `POST /surveys/{id}/duplicate` | admin/analyst/superadmin | 201; full config |
| `DELETE /surveys/{id}` | admin/analyst/superadmin | 204; service enforces owner/admin + lock |
| `PATCH /surveys/{id}/status` | admin/analyst/superadmin | toggle; bypasses lock |
| `GET /surveys/templates/fies` | admin/analyst/superadmin | static structure |

Ordering of path routes: declare `/surveys/templates/fies` **before** `/surveys/{id}`
so the literal path is not captured by the UUID param. Include `responses={...}` OpenAPI
docs like `measurements.py`.

#### 4. Register router — `app/api/v1/router.py`

`v1_router.include_router(surveys.router, tags=["Surveys V1"])`.

### Success Criteria

#### Automated Verification
- [x] `poetry run pre-commit run --all-files`
- [x] App boots: `poetry run python -c "from app.main import app"` (8 survey routes registered, `/templates/fies` ordered before `/{survey_id}`)
- [ ] Integration suite green (Phase 6) — **blocked: Docker unavailable**

#### Manual Verification
- [ ] `/docs` shows all eight survey routes under "Surveys V1".
- [ ] `field_worker` token → 403 on every survey route.
- [ ] Create → GET returns questions in `position` order with nested options.
- [ ] Duplicate of "X" yields "X (copy)"; duplicating again yields "X (copy 2)".
- [ ] `PATCH .../status` toggles `is_active` and is reflected in `GET` + list filter.
- [ ] Error bodies use `application/problem+json` with correct titles/status.

---

## Phase 6: Tests

### Unit — `tests/unit/test_survey_service.py` (mocked UoW/repos)
- Name uniqueness pre-check → `AlreadyExistsError` (create + rename w/ `exclude_id`).
- Scope validation both directions (targeted⇒≥1 & unknown est.⇒`EstablishmentNotFoundError`; generic⇒0 rejects supplied ids).
- Question/option validation: 1–30 bound, choice ⇒ 2–20 options, non-choice ⇒ options rejected, duplicate-option rejection, length limits.
- Permission gates: create roles; edit = owner-or-admin (analyst editing another's → `ForbiddenError`; admin editing any → ok).
- `PUT` reconciliation: insert (no id) / update (known id) / delete (missing id); cross-survey id → error.
- Duplicate name-suffix logic incl. `(copy 2)` collision path.
- Edit-lock stub: no-op while `response_count == 0`; raises `SurveyLockedError` when forced > 0.
- Status toggle allowed regardless of `response_count`.

### Integration — `tests/integration/test_surveys.py` (Testcontainers + HTTP)
- create → get → put(reconcile) → duplicate → delete round-trips.
- `lower(name)` unique index: case-insensitive collision → 409.
- Cascade deletes: deleting a survey removes questions/options/establishments.
- Role 401 (no token) / 403 (`field_worker`).
- `GET /surveys` listing: name search, `created_by`, `scope`, `is_active` filters + pagination + sort.
- `GET /surveys/templates/fies` returns the 8-item structure.
- `PATCH /surveys/{id}/status` round-trip.

### Success Criteria
- [x] `poetry run pytest tests/unit/` (310 passed; 35 new survey-service tests)
- [ ] Full suite (Docker required): `poetry run pytest` — **blocked: Docker unavailable** (21 survey integration tests written; collect cleanly via `--collect-only`)
- [ ] Coverage holds ≥80%: `poetry run pytest --cov=app` — **blocked: Docker unavailable**

---

## Testing Strategy

Follow the existing split: unit tests exercise `SurveyService` with mocked repositories
(`tests/unit/conftest.py` factories); integration tests exercise the full HTTP + DB stack
via Testcontainers (`tests/integration/conftest.py`). Assert both success and RFC 7807
error shapes.

## Performance Considerations

- Questions/options/establishments eager-loaded via `lazy="selectin"` — avoids N+1 when
  returning full configs.
- List endpoint uses `execute_paginated` (LIMIT/OFFSET + count) — no unbounded queries.
- New indexes: `uq_surveys_lower_name`, `survey_questions.survey_id`,
  `survey_question_options.question_id`.
- Aggregate sizes are tiny (≤30 questions, ≤20 options each) — reconciliation cost is negligible.

## Migration Notes

- Single Alembic revision creating four tables + two enums + the functional unique index.
- Autogenerate will **not** produce the `lower(name)` index — add it by hand.
- Rollback: `poetry run alembic downgrade -1` drops tables (children first) and both enums.
- No data backfill (greenfield).

## References

- Story: US "Crear y configurar encuestas FIES y personalizadas" (CA1–CA9).
- ADRs: [ADR-0001 declarative API](../adr/0001-declarative-whole-survey-authoring-api.md), [ADR-0002 FIES-as-template](../adr/0002-fies-as-template-no-survey-type.md).
- Reference slice: `app/models/measurement.py`, `app/domain/measurement.py`, `app/repositories/measurement_repository.py`, `app/services/measurement_service.py`, `app/api/v1/measurements.py`.
- Conventions: `docs/conventions.md`, `docs/architecture.md`, `docs/auth.md`.

### FIES wording sources

- FAO — *La escala de experiencia de inseguridad alimentaria (FIES)*: <https://openknowledge.fao.org/server/api/core/bitstreams/f0cb3175-4ac0-4e7f-8daa-70c38d768ff4/content>
- FAO — *Measuring hunger / FIES* hub: <https://www.fao.org/measuring-hunger/en>
- Validated Spanish item wording + FAO labels (Colombia/Guatemala/México), *Salud Pública de México* (SciELO): <https://www.scielo.org.mx/scielo.php?script=sci_arttext&pid=S0036-36342018000500012>
- DANE (Colombia) — FIES nota metodológica: <https://www.dane.gov.co/files/operaciones/FIES/Nota-metologica-FIES.pdf>
- Acción contra el Hambre — las 8 preguntas de la escala FIES: <https://accionsocial.accioncontraelhambre.org/es/actualidad/como-medir-la-inseguridad-alimentaria-conoce-las-8-preguntas-clave-la-escala-fies>
