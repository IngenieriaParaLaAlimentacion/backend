# Subjects Offline-First Idempotent Create Implementation Plan

## Overview

Adapt `POST /api/v1/subjects` so the mobile app can create subjects **offline-first**:
the client generates the subject's UUID and sends it as the primary key, repeated
submissions are idempotent (safe retries), and a cross-device duplicate (same DNI
under a different id) is surfaced as a `409` carrying the **canonical subject** so the
device can remap its local child records. No database schema change is required.

## Current State Analysis

- `POST /api/v1/subjects` (`app/api/v1/subjects.py:19-39`) calls
  `SubjectService.create_subject` and always returns `201`.
- `SubjectService.create_subject` (`app/services/subject_service.py:29-56`) inserts the
  subject, appends a `SUBJECT_CREATED` audit event, and commits. PK is **server-generated**
  (`Subject.id` default `uuid.uuid4`, `app/models/subject.py:28`).
- DNI uniqueness is enforced by `uq_subjects_dni`
  (`alembic/versions/eb850f66c679_...py:25`) plus model-level `unique=True`
  (`app/models/subject.py:29`).
- `SubjectRepository.create` (`app/repositories/subject_repository.py:20-46`) flushes and
  translates any `IntegrityError` into `UniqueConstraintError`, which the service maps to
  `SubjectAlreadyExistsError` → **409** today (`app/exceptions/exception_handlers.py:32`,
  `tests/integration/test_subject.py:122`).
- Errors use an RFC 7807 `problem+json` envelope built by `_build_error_response`
  (`app/exceptions/exception_handlers.py:14-25`).
- The UnitOfWork dependency (`app/core/dependencies.py:43-46`) opens a fresh session per
  request; `IUnitOfWork.__aexit__` (`app/core/interfaces/unit_of_work.py:34-37`) rolls back
  on exception and always closes — so read-only (replay) and raising (conflict) paths need
  no explicit commit.

### Key Discoveries

- **No migration needed.** The `id` column already accepts a UUID; we simply stop relying on
  the server default when the client supplies one. Making the request field optional keeps the
  backoffice flow (no id) working unchanged.
- A duplicate DNI **without** a client id (backoffice) still maps to `409` — the status code
  is unchanged; we only enrich the body. The existing test `test_duplicate_dni_returns_409`
  stays valid.
- `SubjectService` already imports from `app.schemas.subject_schema`
  (`app/services/subject_service.py:14`), so building the canonical body in the service with
  `SubjectResponse` is consistent with the existing layering.
- `BaseError.__init__` is called positionally by every subclass, so adding an optional
  `extensions` parameter is backward-compatible.

## Desired End State

`POST /api/v1/subjects` behaves as an idempotent get-or-create keyed on the client UUID:

| Situation | Status | Body |
|---|---|---|
| New `id` + new DNI (or no `id` + new DNI) | `201 Created` | the created subject |
| Same `id` already exists (offline retry) | `200 OK` | the existing subject (no new event) |
| DNI already exists under a different/absent `id` | `409 Conflict` | `problem+json` with a `canonical_subject` extension |
| Validation failure | `422` | standard validation error |

Verification: the integration suite in `tests/integration/test_subject.py` covers all four
rows; the audit log gains exactly one `SUBJECT_CREATED` event per *created* subject and none
for replays or conflicts.

## What We're NOT Doing

- **No batch/bulk endpoint.** Single-subject idempotent create is the offline-first
  foundation; a generic per-item-result sync envelope (covering measurements, surveys, iron
  values) is deferred to a later plan once sync volume justifies it.
- **No change to the role/permission model.** The endpoint keeps `require_any`. The known
  mismatch between `require_any` and the "field workers only" wording in the
  endpoint description is **intentionally left untouched** here and should be tracked
  separately.
- **No DNI mutability change.** `PATCH /subjects/{id}` still allows DNI correction; promoting
  DNI to an immutable natural key is out of scope.
- **No subjects-without-DNI support.** DNI remains required; populations that may lack a DNI
  are a separate design concern.
- **Create never mutates.** If the supplied `id` already exists, the stored subject is
  returned as-is (200); field corrections go through `PATCH`, not by re-POSTing.

## Implementation Approach

Layered, smallest-touch changes following `api → service → repository`:

1. **Schema** — add an optional client-supplied `id` to `SubjectRequest`.
2. **Repository** — accept the optional `id` and wrap the insert in a **savepoint**
   (`begin_nested`) so the session survives an `IntegrityError` and the service can re-query.
3. **Service** — implement get-or-create: pre-check by id (replay), insert, and on conflict
   distinguish an id race (replay → 200) from a DNI collision (→ enriched 409).
4. **Exceptions** — let `problem+json` carry extension members; enrich
   `SubjectAlreadyExistsError` with the canonical subject.
5. **API** — return `200` on replay vs `201` on create; document `200`/`409` in OpenAPI.
6. **Tests + mobile contract doc.**

---

## Phase 1: Request schema accepts a client-generated id

### Overview
Allow the client to supply the subject UUID; keep it optional for backward compatibility.

### Changes Required

#### Schema
**File**: `app/schemas/subject_schema.py`
**Changes**: Add an optional `id` field to `SubjectRequest` (`UUID` is already imported).

```python
class SubjectRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID for offline-first idempotency. When provided it "
            "becomes the subject's primary key and repeated submissions with the same "
            "id are idempotent. When omitted, the server generates one."
        ),
    )
    dni: int = Field(ge=1, le=99_999_999)
    # ... unchanged fields ...
```

### Success Criteria

#### Automated Verification
- [x] Lint + format pass exactly as CI does: `poetry run pre-commit run --all-files`
- [x] Unit tests pass: `poetry run pytest tests/unit/`

#### Manual Verification
- [ ] `/docs` shows the optional `id` field on the create request body.

---

## Phase 2: Repository — accept id and survive conflicts

### Overview
Pass the optional `id` through to the model and wrap the flush in a savepoint so a unique
violation does not poison the session (the service re-queries afterwards).

### Changes Required

#### Repository
**File**: `app/repositories/subject_repository.py`
**Changes**: `create` accepts `id`; build kwargs so a `None` id falls back to the server
default; flush inside `begin_nested()`.

```python
async def create(
    self,
    *,
    id: UUID | None,
    dni: int,
    sex: Sex,
    name: str,
    last_name: str,
    birth_date: datetime.date,
    is_rural: bool,
    is_indigenous: bool,
) -> Subject:
    """Persist a new subject. ``id`` is optional; when None the server generates it.

    Raises:
        UniqueConstraintError: If the id or DNI violates a unique constraint. The
        caller is responsible for re-querying to decide the outcome.
    """
    fields = dict(
        dni=dni, sex=sex, name=name, last_name=last_name,
        birth_date=birth_date, is_rural=is_rural, is_indigenous=is_indigenous,
    )
    if id is not None:
        fields["id"] = id
    subject = Subject(**fields)
    self.db.add(subject)
    try:
        async with self.db.begin_nested():
            await self.db.flush()
    except IntegrityError:
        raise UniqueConstraintError("subject", (id, dni))
    await self.db.refresh(subject)
    return subject
```

`get_by_id` and `get_by_dni` already exist (`subject_repository.py:63-70`) and are used by the
service in the next phase. `UUID` import: add `from uuid import UUID` (currently only
`datetime` and `from uuid import UUID` — confirm the import line).

### Success Criteria

#### Automated Verification
- [x] Lint + format pass: `poetry run pre-commit run --all-files`
- [x] Full suite passes (Docker required): `poetry run pytest tests/integration/test_subject.py`

#### Manual Verification
- [ ] Creating with a client id persists that exact UUID (GET by it returns the subject).

---

## Phase 3: Service — idempotent get-or-create with conflict reconciliation

### Overview
Implement the four-way outcome. Return `(subject, created)` so the route can choose
`200` vs `201`; raise an enriched `SubjectAlreadyExistsError` for a true DNI collision.

### Changes Required

#### Service
**File**: `app/services/subject_service.py`
**Changes**: Import `SubjectResponse`; rewrite `create_subject`.

```python
from app.schemas.subject_schema import (
    SubjectRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)

async def create_subject(
    self, data: SubjectRequest, actor_id: UUID
) -> tuple[SubjectDomain, bool]:
    """Idempotently register a subject.

    Returns a ``(subject, created)`` tuple: ``created`` is True for a brand-new
    subject (201) and False for an idempotent replay of an existing id (200).

    Raises:
        SubjectAlreadyExistsError: If the DNI already belongs to a different
        subject. The exception carries the canonical subject so the caller can
        remap local references.
    """
    # Idempotent replay: same client id already stored.
    if data.id is not None:
        existing = await self.uow.subject_repo.get_by_id(data.id)
        if existing is not None:
            return SubjectDomain.from_db(existing), False

    try:
        subject = await self.uow.subject_repo.create(
            id=data.id,
            dni=data.dni,
            sex=data.sex,
            name=data.name,
            last_name=data.last_name,
            birth_date=data.birth_date,
            is_rural=data.is_rural,
            is_indigenous=data.is_indigenous,
        )
    except UniqueConstraintError:
        # Concurrent insert of the same id (race) -> treat as replay.
        if data.id is not None:
            raced = await self.uow.subject_repo.get_by_id(data.id)
            if raced is not None:
                return SubjectDomain.from_db(raced), False
        # Otherwise the DNI belongs to another subject -> surface the canonical one.
        canonical = await self.uow.subject_repo.get_by_dni(data.dni)
        canonical_body = (
            SubjectResponse.model_validate(canonical).model_dump(mode="json")
            if canonical is not None
            else None
        )
        raise SubjectAlreadyExistsError(data.dni, canonical=canonical_body)

    await self.uow.subject_event_repo.append(
        subject_id=subject.id,
        actor_id=actor_id,
        event_type=SubjectEventType.SUBJECT_CREATED,
    )
    await self.uow.commit()
    return SubjectDomain.from_db(subject), True
```

### Success Criteria

#### Automated Verification
- [x] Lint + format pass: `poetry run pre-commit run --all-files`
- [x] Unit tests pass: `poetry run pytest tests/unit/test_subject_service.py`

#### Manual Verification
- [ ] Replaying the same id returns the same subject and adds no second audit event.

---

## Phase 4: Exceptions — carry the canonical subject in problem+json

### Overview
Let any `BaseError` attach RFC 7807 extension members, and enrich
`SubjectAlreadyExistsError` with the canonical subject.

### Changes Required

#### Domain exceptions
**File**: `app/exceptions/domain_exceptions.py`
**Changes**: Add optional `extensions` to `BaseError`; add optional `canonical` to
`SubjectAlreadyExistsError`.

```python
class BaseError(Exception):
    def __init__(self, title: str, details: str, extensions: dict | None = None):
        self.title = title
        self.details = details
        self.extensions = extensions or {}
        super().__init__(f"{title}: {details}")


class SubjectAlreadyExistsError(AlreadyExistsError):
    def __init__(self, dni: int, canonical: dict | None = None):
        super().__init__(
            "Subject already exists",
            f"A subject with DNI {dni} already exists.",
            extensions={"canonical_subject": canonical} if canonical else None,
        )
```

#### Exception handler
**File**: `app/exceptions/exception_handlers.py`
**Changes**: Merge `extensions` into the response content.

```python
def _build_error_response(e: BaseError, request: Request, status_code: int):
    content = {
        "type": f"/errors/{e.title.lower().replace(' ', '-')}",
        "title": e.title,
        "status": status_code,
        "detail": e.details,
        "instance": request.url.path,
    }
    content.update(getattr(e, "extensions", {}) or {})
    return JSONResponse(
        status_code=status_code,
        content=content,
        media_type="application/problem+json",
    )
```

### Success Criteria

#### Automated Verification
- [x] Lint + format pass: `poetry run pre-commit run --all-files`
- [x] Existing exception/handler behavior unbroken: `poetry run pytest tests/`

#### Manual Verification
- [ ] A DNI collision returns `409` whose body includes `canonical_subject` with the
      existing subject's `id`, `dni`, `name`, `last_name`, `sex`.

---

## Phase 5: API route — 200 vs 201 and OpenAPI docs

### Overview
Translate the service `(subject, created)` tuple into the right status code and document the
new responses.

### Changes Required

#### Route
**File**: `app/api/v1/subjects.py`
**Changes**: Inject `Response`; set `200` on replay; add `200` and clarify `409` in the
`responses` map. **Do not** alter the "field workers only" description line
(out of scope).

```python
from fastapi import APIRouter, Depends, Query, Response, status

@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new subject",
    description="Creates a new subject. Accessible by field workers only.",
    responses={
        status.HTTP_200_OK: {
            "description": "Subject already existed; idempotent replay of the same id."
        },
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_409_CONFLICT: {
            "description": "A subject with this DNI already exists under a different "
            "id; the canonical subject is returned in `canonical_subject`."
        },
    },
)
async def create_subject(
    data: SubjectRequest,
    response: Response,
    user: UserActor = Depends(require_any),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    """Register a new subject (idempotent on the client-supplied id)."""
    subject, created = await service.create_subject(data, actor_id=user.user_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return SubjectResponse.model_validate(subject)
```

### Success Criteria

#### Automated Verification
- [x] Lint + format pass: `poetry run pre-commit run --all-files`
- [x] Full suite passes (Docker required): `poetry run pytest`

#### Manual Verification
- [ ] New id + new DNI → `201`; same id again → `200`; same DNI different id → `409` with
      `canonical_subject`; omitting id still → `201`.
- [ ] No regression in GET / list / PATCH endpoints.

---

## Phase 6: Tests

### Overview
Cover the new outcomes at both layers.

### Changes Required

#### Integration
**File**: `tests/integration/test_subject.py`
- Add an `_upload_with_id(client, headers, subject_id, **overrides)` helper.
- Extend `test_duplicate_dni_returns_409` to assert the `canonical_subject` extension is
  present and its `id`/`dni` match the first subject.
- `test_client_supplied_id_is_used_as_pk` — POST with `id=A`; GET `/{A}` returns it.
- `test_same_id_replay_returns_200` — POST `id=A` twice; second is `200` with the same body.
- `test_replay_creates_no_second_event` (in `TestSubjectEventLog`) — exactly one
  `SUBJECT_CREATED` after a replay.
- `test_dni_conflict_different_id_returns_409_with_canonical` — POST `id=A,dni=D` (201),
  POST `id=B,dni=D` → `409`, body `canonical_subject.id == A`.
- `test_missing_id_still_returns_201` — current backoffice behavior preserved.

#### Unit
**File**: `tests/unit/test_subject_service.py`
- Mirror the existing UoW-mocking pattern in that file to cover, against a faked
  `subject_repo`: replay-by-id (returns `(subject, False)`, no event/commit), create
  (returns `(subject, True)`, appends event + commits), id race on `UniqueConstraintError`
  (returns `(raced, False)`), and DNI collision (raises `SubjectAlreadyExistsError` whose
  `extensions["canonical_subject"]` is populated).

### Success Criteria

#### Automated Verification
- [ ] Unit tests pass: `poetry run pytest tests/unit/`
- [x] Full suite passes (Docker required): `poetry run pytest`
- [x] Coverage holds: `poetry run pytest --cov=app`

#### Manual Verification
- [ ] None beyond the automated assertions.

---

## Phase 7: Mobile contract documentation

### Overview
A standalone reference for the mobile team describing how to consume the endpoint
offline-first. (See the full contract in **Mobile Contract Consumption** below.)

### Changes Required
**File**: `docs/mobile/subjects-offline-sync.md` (new)
**Changes**: Document id generation, the local sync state machine, the request shape, the
response→action table, sync ordering of child records, and the two-device dedup walkthrough
— the content of the section below.

### Success Criteria
#### Manual Verification
- [ ] A mobile engineer can implement the sync loop from the doc without reading the backend.

---

## Mobile Contract Consumption

How the mobile app should use `POST /api/v1/subjects` for offline-first.

### 1. Generate the id on the device
At the moment a subject is created locally (online or offline), the device mints a **UUID**
and uses it as both the local primary key and the value sent to the server. Prefer **UUIDv7**
(time-ordered → better DB index locality) when the platform supports it; **UUIDv4** is a fine
universal fallback. All locally-created child records (measurements, surveys, iron values)
reference this id **immediately** — they never wait for the server.

### 2. Local sync state machine
Track a status per locally-created subject: `PENDING → SYNCING → SYNCED | CONFLICT | ERROR`.
Because create is idempotent on the id, retries are always safe.

### 3. Request
```http
POST /api/v1/subjects
Authorization: Bearer <token>
Content-Type: application/json

{
  "id": "018f6e2a-7c3a-7e21-9b6a-2b1d3c4e5f60",
  "dni": 30111222,
  "sex": "male",
  "name": "Juan",
  "last_name": "Perez",
  "birth_date": "2010-01-01",
  "is_rural": false,
  "is_indigenous": false
}
```

### 4. Response → action
| Response | Meaning | Mobile action |
|---|---|---|
| `201 Created` | New subject; server id == sent id | Mark `SYNCED`. Nothing to remap. |
| `200 OK` | Same id already existed (a prior attempt actually landed) | Mark `SYNCED`. id unchanged. |
| `409 Conflict` (`canonical_subject` in body) | This DNI already exists under a different id | Read `canonical_subject.id`; **remap** local child records from the local id to the canonical id; adopt the canonical subject; mark `SYNCED`. If local fields differ from canonical, surface for user reconciliation. |
| `422` | Invalid payload | Mark `ERROR`, surface to user; **do not** blind-retry. |
| `401` | Token expired/invalid | Refresh token, retry. |
| `5xx` / network error | Transient | Keep `PENDING`, retry with exponential backoff (safe — idempotent). |

The `409` body (RFC 7807 `problem+json`):
```json
{
  "type": "/errors/subject-already-exists",
  "title": "Subject already exists",
  "status": 409,
  "detail": "A subject with DNI 30111222 already exists.",
  "instance": "/api/v1/subjects",
  "canonical_subject": {
    "id": "018f6e2a-1111-7e21-9b6a-aaaaaaaaaaaa",
    "dni": 30111222,
    "name": "Juan",
    "last_name": "Perez",
    "sex": "male"
  }
}
```

### 5. Sync ordering
Always sync a subject **before** its child records (children FK to the subject id). After a
`409` remap, re-point children to the canonical id **before** syncing them.

### 6. Two-device dedup walkthrough
- Device 1 registers Juan offline: `id=A, dni=D`, takes measurements referencing `A`.
- Device 2 registers the same Juan offline: `id=B, dni=D`, takes a measurement referencing `B`.
- Device 1 syncs → `201` (subject `A`). Its measurements sync against `A`.
- Device 2 syncs the subject → `409` with `canonical_subject.id == A`. Device 2 remaps its
  local children `B → A`, adopts `A`, then syncs its measurements against `A`.
- Result: one canonical subject `A`, all measurements attached to it. No duplicates.

### 7. Idempotency guarantee & limits
Re-POSTing the same `id` never creates a duplicate (200/201 are both terminal-success). The
endpoint requires a DNI; subjects without a DNI cannot use DNI-dedup (out of scope). Create
never updates an existing subject — use `PATCH /subjects/{id}` for corrections.

---

## Testing Strategy

### Unit Tests
`tests/unit/test_subject_service.py` — the four service outcomes (created, replay-by-id,
id-race replay, DNI conflict with populated `canonical_subject`) against a mocked UoW.

### Integration Tests
`tests/integration/test_subject.py` (Testcontainers, Docker required) — the full HTTP
contract: client-supplied id persisted as PK, `200` replay with no duplicate event, `409`
with `canonical_subject`, and the preserved no-id `201` path.

### Manual Testing Steps
1. `/docs`: create with a client `id` → `201`; repeat → `200`.
2. Create `id=A,dni=D`, then `id=B,dni=D` → `409` with `canonical_subject.id == A`.
3. Create without `id` → `201` (backoffice path).
4. Create the same no-id DNI twice → `409` enriched body.

## Performance Considerations

- The conflict path adds at most one extra indexed lookup (`get_by_dni` on `uq_subjects_dni`,
  or `get_by_id` on the PK) and only on the rare conflict/replay branch. The happy path is a
  single insert.
- `begin_nested()` issues a SAVEPOINT only around the insert; negligible overhead.
- No new indexes required (PK and `uq_subjects_dni` already cover all lookups).

## Migration Notes

**None.** The `id` column already accepts a client-supplied UUID, and `uq_subjects_dni`
already exists. No Alembic revision, backfill, or rollback is involved.

## References

- Current endpoint: `app/api/v1/subjects.py:19-39`
- Current service: `app/services/subject_service.py:29-56`
- Repository: `app/repositories/subject_repository.py:20-70`
- Model + constraint: `app/models/subject.py:28-29`,
  `alembic/versions/eb850f66c679_add_subjects_constraints_and_indexes.py:25`
- Error envelope: `app/exceptions/exception_handlers.py:14-33`
- UoW lifecycle: `app/core/interfaces/unit_of_work.py:31-40`
- Existing tests: `tests/integration/test_subject.py`, `tests/unit/test_subject_service.py`
- Conventions: `docs/conventions.md`, `docs/architecture.md`, `docs/auth.md`
