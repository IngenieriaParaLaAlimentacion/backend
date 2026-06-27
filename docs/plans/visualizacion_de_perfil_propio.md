# Own Profile View (`GET /api/v1/users/me`) Implementation Plan

## Overview

Expose a single authenticated read endpoint that returns the current user's
profile (name, last name, email, role) and — **only for `field_worker`
users** — their associated establishments, each annotated with its approval
status (`approved` / `pending` / `rejected`). This is the backend support for the
mobile "Visualización de perfil propio" user story
(`docs/user-stories/visualizacion_de_perfil_propio.md`).

## Current State Analysis

- **No profile/`/me` endpoint exists.** `app/api/v1/router.py:7-10` mounts only
  `admin`, `auth`, `establishments`, `subjects`.
- The auth dependency we need already exists: `require_any`
  (`app/core/dependencies.py:113`) accepts any authenticated role and yields a
  `UserActor(user_id, role)`. Already used in `app/api/v1/subjects.py:56`.
- **Domain types are already scaffolded but unused.**
  `EstablishmentWithStatusDomain` (`app/domain/establishment.py:21-25`, fields
  `id, name, address, status: str`) and `ApprovedFieldWorkerDomain`
  (`app/domain/user.py:62-67`) exist in code but are referenced nowhere in
  production — they anticipate exactly this view.
- The exact vertical pattern to mirror is the admin users slice: route
  `app/api/v1/admin.py:38-74` → service `app/services/admin_service.py:104-153`
  → repos. It already builds users-with-establishments and has the helper
  `_get_establishments_per_user` (`admin_service.py:44-68`).
- **Status serialization is already conventional.** Schema fields are typed
  `status: str`, the route passes the enum directly (`admin.py:60`), and Pydantic
  emits the enum *value* — proven by `tests/integration/test_admin.py:309`
  (`item["status"] == UserStatus.PENDING_VALIDATION`, i.e. `"pending_validation"`).
- **No migration needed** — `User`, `Establishment`, and `user_establishments`
  (with its `status` column) all already exist.

### Key Discoveries / Gotchas

- **Token `sub` is a string.** `create_access_token` stores `"sub": str(user_id)`
  (`app/core/security.py:44`) and `UserActor(user_id=payload["sub"], ...)`
  (`app/core/dependencies.py:79`) does no coercion. So `actor.user_id` is a
  **`str`**, while `UserRepository.get_by_id(user_id: UUID)`
  (`app/repositories/user_repository.py:33-35`) uses `db.get(User, user_id)`.
  The service **must convert `actor.user_id` to `UUID`** before querying.
- **Never touch the lazy `User.establishments` relationship under async.**
  `get_by_id` uses `db.get` and does *not* eager-load relationships; accessing
  `user.establishments` would trigger a lazy load and raise. Fetch establishments
  via `user_establishment_repo.get_by_user_id` + `establishment_repo.find_by_ids`
  instead (this is what the admin slice already does).
- `user_establishment_repo.get_by_user_id(user_id)`
  (`app/repositories/user_establishment_repository.py:39-44`) returns
  `list[UserEstablishment]`, each carrying `establishment_id` **and** `status` —
  exactly the per-relation status we need.
- `establishment_repo.find_by_ids(ids)`
  (`app/repositories/establishment_repository.py:21-27`) returns the matching
  establishments and **silently skips missing ids** — safe for read assembly.

## Desired End State

`GET /api/v1/users/me` with a valid bearer token returns `200` and:

```jsonc
// field_worker with 2 establishments
{
  "id": "…", "email": "…", "name": "…", "last_name": "…",
  "role": "field_worker",
  "establishments": [
    { "id": "…", "name": "Centro A", "address": "Calle A 123", "status": "approved" },
    { "id": "…", "name": "Centro B", "address": "Calle B 456", "status": "pending" }
  ]
}

// field_worker with none  -> empty list (CA3: app shows "request access")
{ "...": "...", "role": "field_worker", "establishments": [] }

// admin / analyst             -> null (no establishments section)
{ "...": "...", "role": "analyst", "establishments": null }
```

Verification: integration tests pass against a real Postgres container; manual
`curl`/Swagger check returns the shapes above for each role.

## Decisions (resolved)

1. **Placement:** new `users` module + `UserService`, path `GET /api/v1/users/me`.
2. **`establishments` field:** `null` for admin/analyst; a list (`[]` when
   none) for field workers — lets the app distinguish "no section" from "empty section"
   per CA3.
3. **Status format:** the existing `UserEstablishmentStatus` enum value
   (`approved`/`pending`/`rejected`) serialized as `str`, following the
   established convention. The mobile app localizes to Aceptado/Pendiente/Rechazado.

## What We're NOT Doing

- **CA2 (edit profile):** the edit screen is client navigation; the edit endpoint
  is a separate story. Out of scope.
- **CA3 "request access" action:** for an active field worker with zero establishments,
  the backend only returns `[]`. The request-access submission flow is a separate
  story. Out of scope.
- No changes to authentication, token issuance, or the DB schema.
- No pagination on establishments (a field worker's set is small and bounded).

## Implementation Approach

Mirror the admin users vertical slice but for a single self-resolved user. The
service reads the user by the token's id, and — only when the role is
`field_worker` — assembles `EstablishmentWithStatusDomain` items by
joining the association rows (status) with establishment details. A new
`ProfileDomain` carries `establishments: list[...] | None` so a single return type
expresses both "no section" (`None`) and "empty section" (`[]`). The route maps
the domain to a `ProfileResponse`. TDD: unit tests for the service first, then
integration tests for the endpoint.

---

## Phase 1: Domain type + response schemas

### Overview

Add the single return domain type and the Pydantic response schemas. No behavior
yet.

### Changes Required:

#### 1. Profile domain type

**File**: `app/domain/user.py`
**Changes**: Add a `ProfileDomain` dataclass reusing `BaseUserDomain` fields, with
a nullable establishments list. (`EstablishmentWithStatusDomain` is already
imported at `app/domain/user.py:5`.)

```python
@dataclass
class ProfileDomain(BaseUserDomain):
    """Current user's profile. ``establishments`` is None for non-field-workers,
    and a (possibly empty) list for field workers."""

    establishments: list[EstablishmentWithStatusDomain] | None = None
```

#### 2. Response schemas

**File**: `app/schemas/user_schema.py` (new)
**Changes**: New module with the establishment-with-status item and the profile
envelope. Follows the `from_attributes` convention used across `app/schemas/`.

```python
from uuid import UUID

from pydantic import BaseModel


class EstablishmentWithStatusResponse(BaseModel):
    id: UUID
    name: str
    address: str
    status: str

    model_config = {"from_attributes": True}


class ProfileResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    establishments: list[EstablishmentWithStatusResponse] | None = None

    model_config = {"from_attributes": True}
```

### Success Criteria:

#### Automated Verification:

- [x] Lint/format clean: `poetry run ruff check . && poetry run ruff format --check .`
- [x] Imports resolve: `poetry run python -c "from app.domain.user import ProfileDomain; from app.schemas.user_schema import ProfileResponse, EstablishmentWithStatusResponse"`

#### Manual Verification:

- [x] `ProfileResponse.establishments` defaults to `None` (non-field-worker case) and accepts `[]`.

---

## Phase 2: `UserService.get_profile` (TDD)

### Overview

Business logic: resolve the user from the actor, and assemble status-annotated
establishments for field workers only. Write unit tests first (RED), then implement
(GREEN).

### Changes Required:

#### 1. Unit tests (write first)

**File**: `tests/unit/test_user_service.py` (new)
**Changes**: Use the AsyncMock `make_uow` factory pattern from
`tests/unit/conftest.py:34-59`. Cover:

- **Field worker with mixed-status establishments** → returns `ProfileDomain` whose
  `establishments` is a list of `EstablishmentWithStatusDomain` with the correct
  `status` per relation, and correct name/address joined from establishment data.
- **Field worker with no relations** → `establishments == []`.
- **Analyst** → `establishments is None`; association repo **not** queried.
- **Admin** → `establishments is None`.
- **User id from token not found** → raises `UserNotFoundError`.
- **`actor.user_id` passed as a `str`** (as the real dependency produces) → service
  converts to `UUID` and still resolves (assert `get_by_id` called with a `UUID`).
- A relation whose establishment id is missing from `find_by_ids` is skipped
  (defensive; mirrors `find_by_ids` semantics).

#### 2. Service implementation

**File**: `app/services/user_service.py` (new)
**Changes**: New `UserService` backed by the UnitOfWork, mirroring `AdminService`'s
constructor and helper style.

```python
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentWithStatusDomain
from app.domain.user import ProfileDomain, UserActor, UserRole
from app.exceptions.domain_exceptions import UserNotFoundError


class UserService:
    """Service layer for current-user (profile) reads."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_profile(self, actor: UserActor) -> ProfileDomain:
        """Return the authenticated user's profile.

        Establishments are included only for field workers; for other
        roles the field is None (no establishments section).

        Raises:
            UserNotFoundError: If the token's user no longer exists.
        """
        user_id = UUID(str(actor.user_id))
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))

        establishments = None
        if user.role == UserRole.FIELD_WORKER:
            establishments = await self._get_establishments_with_status(user_id)

        return ProfileDomain(
            id=user.id,
            email=user.email,
            name=user.name,
            last_name=user.last_name,
            role=user.role,
            status=user.status,
            establishments=establishments,
        )

    async def _get_establishments_with_status(
            self, user_id: UUID
    ) -> list[EstablishmentWithStatusDomain]:
        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        if not relations:
            return []

        establishments = await self.uow.establishment_repo.find_by_ids(
            [relation.establishment_id for relation in relations]
        )
        by_id = {establishment.id: establishment for establishment in establishments}

        result: list[EstablishmentWithStatusDomain] = []
        for relation in relations:
            establishment = by_id.get(relation.establishment_id)
            if establishment is None:
                continue
            result.append(
                EstablishmentWithStatusDomain(
                    id=establishment.id,
                    name=establishment.name,
                    address=establishment.address,
                    status=relation.status,
                )
            )
        return result
```

> Note: `relation.status` is a `UserEstablishmentStatus` (a `str`-Enum); assigning
> it to the `str` field mirrors how `admin.py:60` passes `user.status`, and
> Pydantic serializes its value. Use `.value` only if a unit test wants an exact
> `str` in the domain object.

### Success Criteria:

#### Automated Verification:

- [x] New unit tests pass: `poetry run pytest tests/unit/test_user_service.py`
- [x] No regressions in unit suite: `poetry run pytest tests/unit/`
- [x] Lint/format clean: `poetry run ruff check . && poetry run ruff format --check .`

#### Manual Verification:

- [x] Service never accesses `user.establishments` (the lazy relationship).

---

## Phase 3: Wire the endpoint

### Overview

Add the service provider, the route, and mount the router.

### Changes Required:

#### 1. Service dependency provider

**File**: `app/core/dependencies.py`
**Changes**: Add `get_user_service` next to the other providers (`:21-42`), and the
import.

```python
from app.services.user_service import UserService


async def get_user_service() -> AsyncGenerator[UserService, None]:
    """Provide a UserService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield UserService(uow)
```

#### 2. Route handler

**File**: `app/api/v1/users.py` (new)
**Changes**: New router with the single `GET /me` endpoint, mirroring the
documentation/error style of `app/api/v1/admin.py:38-74`.

```python
from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_user_service, require_any
from app.domain.user import UserActor
from app.schemas.user_schema import EstablishmentWithStatusResponse, ProfileResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users")


@router.get(
    "/me",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get own profile",
    description="Returns the authenticated user's profile. Field workers "
    "also receive their associated establishments, each with its approval status.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_404_NOT_FOUND: {"description": "Authenticated user no longer exists"},
    },
)
async def get_my_profile(
    actor: UserActor = Depends(require_any),
    service: UserService = Depends(get_user_service),
) -> ProfileResponse:
    profile = await service.get_profile(actor)
    return ProfileResponse(
        id=profile.id,
        email=profile.email,
        name=profile.name,
        last_name=profile.last_name,
        role=profile.role,
        establishments=(
            None
            if profile.establishments is None
            else [
                EstablishmentWithStatusResponse(
                    id=establishment.id,
                    name=establishment.name,
                    address=establishment.address,
                    status=establishment.status,
                )
                for establishment in profile.establishments
            ]
        ),
    )
```

#### 3. Mount the router

**File**: `app/api/v1/router.py`
**Changes**: Add `users` to the import and include its router with a tag.

```python
from app.api.v1 import admin, auth, establishments, subjects, users
...
v1_router.include_router(users.router, tags=["Users V1"])
```

### Success Criteria:

#### Automated Verification:

- [x] App imports and the route is registered: `poetry run python -c "from app.main import app; assert any(getattr(r, 'path', None) == '/api/v1/users/me' for r in app.routes)"`
- [x] Lint/format clean: `poetry run ruff check . && poetry run ruff format --check .`

#### Manual Verification:

- [x] `GET /api/v1/users/me` appears in Swagger UI (`/docs`) under "Users V1" (route registered with the `Users V1` tag, which populates Swagger deterministically).

---

## Phase 4: Integration tests

### Overview

End-to-end HTTP tests against a real Postgres container (Testcontainers, requires
Docker), following `tests/integration/test_admin.py`.

### Changes Required:

#### 1. Endpoint integration tests

**File**: `tests/integration/test_users.py` (new)
**Changes**: Reuse the seeding helpers/patterns from `test_admin.py`
(`create_access_token`, the `_insert_user` pattern at `:130-144`, direct
`AsyncSessionLocal` inserts of `Establishment` and `UserEstablishment`). Cover:

- **401** with no token / malformed token.
- **Analyst** (active, seeded) → `200`, `establishments is None`, and
  `id/email/name/last_name/role` match the seeded user.
- **Admin** → `200`, `establishments is None`.
- **Field worker with establishments** → seed `User` (field worker) + two `Establishment`
  rows + two `UserEstablishment` rows with distinct statuses (e.g. `approved`,
  `pending`); assert the list contains both with the correct `status`, `name`,
  `address` (compare against `UserEstablishmentStatus.<X>` per the convention in
  `test_admin.py:309`).
- **Field worker with no establishments** → `200`, `establishments == []`.
- **Valid token whose user is absent from the DB** (token id never seeded) →
  `404`.

### Success Criteria:

#### Automated Verification:

- [x] New integration tests pass (Docker running): `poetry run pytest tests/integration/test_users.py` — 7 passed
- [x] Full suite green: `poetry run pytest` — 337 passed
- [x] Coverage holds at ≥80% for new code: `poetry run pytest --cov=app --cov-report=term-missing` — 100% on every new file (users.py, user_schema.py, user_service.py, domain/user.py); total 92%

#### Manual Verification:

- [x] `curl -H "Authorization: Bearer <field_worker_token>" localhost:8000/api/v1/users/me` returns establishments with statuses — covered by `test_field_worker_with_establishments_lists_status` (real Postgres).
- [x] Same call with an analyst token returns `"establishments": null` — covered by `test_analyst_has_null_establishments`.

---

## Testing Strategy

### Unit (TDD, Phase 2)

- Drive `UserService.get_profile` with the `make_uow` AsyncMock factory.
- Assert role branching (field worker vs non-field-worker), status mapping, the str→UUID
  conversion of `actor.user_id`, and `UserNotFoundError`.

### Integration (Phase 4)

- Real Postgres via Testcontainers; seed rows directly and assert response shapes
  per role, plus auth (401) and missing-user (404) paths.

### Manual

1. Start the dev server: `poetry run uvicorn app.main:app --reload`.
2. Obtain tokens for a field worker, an analyst, and an admin (`/api/v1/auth/login`).
3. Hit `/api/v1/users/me` with each and confirm the three response shapes.
4. Confirm a field worker with zero establishments returns `[]` (CA3), and a deleted/
   unknown user id returns `404`.

## Performance Considerations

- At most three queries per request: load user, load relations, load
  establishments by ids — and only the last two for field workers. No N+1 (ids are
  batched into `find_by_ids`). Establishment sets per field worker are small.

## Migration Notes

None — no schema changes; `User`, `Establishment`, and `user_establishments`
already exist.

## References

- User story: `docs/user-stories/visualizacion_de_perfil_propio.md`
- Vertical-slice template (admin users): route `app/api/v1/admin.py:38-74`,
  service `app/services/admin_service.py:104-153`
- Auth dependency: `app/core/dependencies.py:113` (`require_any`)
- Reused domain types: `app/domain/user.py:62-67`,
  `app/domain/establishment.py:21-25`
- Reused repos: `app/repositories/user_establishment_repository.py:39-44`,
  `app/repositories/establishment_repository.py:21-27`
- Status-serialization convention: `tests/integration/test_admin.py:309`
- Integration seeding patterns: `tests/integration/test_admin.py:80-144`
