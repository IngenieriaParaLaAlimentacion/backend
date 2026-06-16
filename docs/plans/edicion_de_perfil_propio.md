# Own Profile Edition Implementation Plan

## Overview

Let an authenticated user edit their personal data (`name`, `last_name`) and let
an `establishment_manager` discover and request access to additional
establishments. This is the write-side companion to the already-merged
"Visualización de perfil propio" read endpoint (`GET /api/v1/users/me`).

The work lands entirely on the existing `users` slice (router
`app/api/v1/users.py`, service `app/services/user_service.py`, schemas
`app/schemas/user_schema.py`) plus a small extension to the public establishments
catalog endpoint. **No DB schema change / no Alembic migration** — every column
and table involved already exists (`users.name`, `users.last_name`,
`user_establishments` with its `status`).

## Endpoint surface (decided)

| AC | Method & path | Auth | Behavior |
|---|---|---|---|
| CA1–CA3, CA7 | `PATCH /api/v1/users/me` | any role (`require_any`) | Partial edit of `name`/`last_name`. Returns the updated profile (same shape as `GET /me`). |
| *(extra, requested)* | `GET /api/v1/users/me/establishments` | manager (`get_current_manager`) | The caller's own establishment relations, each annotated with status. |
| CA5, CA6, CA7 | `POST /api/v1/users/me/establishments` | manager (`get_current_manager`) | Request access to one or more establishments (idempotent upsert to `pending`). |
| CA4, CA7 | `GET /api/v1/establishments?available=true` | manager (optional-auth + role gate) | Catalog **minus** the caller's `approved`/`pending` relations (`rejected` reappears). |

## Current State Analysis

- **The read slice is the template.** `GET /api/v1/users/me`
  (`app/api/v1/users.py`) → `UserService.get_profile`
  (`app/services/user_service.py:15`) → assembles `ProfileDomain`
  (`app/domain/user.py:62`) with status-annotated establishments via
  `_get_establishments_with_status` (`user_service.py:43`). `ProfileResponse` /
  `EstablishmentWithStatusResponse` already exist (`app/schemas/user_schema.py`).
- **Writes go through a `UnitOfWork` and an explicit `commit()`.** See
  `AuthService.register_manager` (`app/services/auth_service.py:54-66`) and
  `AdminService.approve_establishments` (`app/services/admin_service.py:155-163`).
  The service providers wrap each call in `async with UnitOfWork()`
  (`app/core/dependencies.py:46-49`).
- **Association repo already has the write primitives we need:**
  `preset_relation(user_id, establishment_id)` inserts a `pending` row
  (`app/repositories/user_establishment_repository.py:16-25`),
  `update_status_for_ids(user_id, ids, status)` updates existing rows (`:46-60`),
  and `get_by_user_id(user_id)` returns every relation with its `status` (`:39-44`).
  The PK is composite `(user_id, establishment_id)`
  (`app/models/user_establishment.py:14-21`) — so the DB already forbids duplicate
  rows; "no duplicates" is structural, not something we enforce by hand.
- **`UserRepository` has no general profile update** — only `update_status`
  (`app/repositories/user_repository.py:103-107`), which uses a Core
  `update(User).where(...).values(...)` statement. We mirror it for `name`/`last_name`.
- **Establishment listing pattern** is paginated + `search` via
  `escape_like`/`execute_paginated` (`app/repositories/establishment_repository.py:46-69`,
  `app/services/establishment_service.py:15-43`,
  `app/api/v1/establishments.py:13-42`). The catalog endpoint is **currently
  unauthenticated**.
- **Existence validation** is `EstablishmentRepository.get_all_by_ids`
  (`establishment_repository.py:29-44`) — raises `EstablishmentNotFoundError`
  (→ 404) if any id is missing. `find_by_ids` (`:21-27`) silently skips missing ids.
- **Error → HTTP mapping** (`app/exceptions/exception_handlers.py`):
  `NotFoundError`→404, `AlreadyExistsError`→409, `BadRequestError`→400,
  `UnauthorizedError`→401, `ForbiddenError`→403, all rendered as
  `application/problem+json`. Pydantic request-validation failures use FastAPI's
  default **422**. `EmptyUpdateRequestError(BadRequestError)` already exists
  (`app/exceptions/domain_exceptions.py:156-163`).
- **Role gating is done per-route via dependencies** (`get_current_admin`,
  `get_current_manager`, `require_any` — `app/core/dependencies.py:89-130`).
  `get_current_manager` accepts `{ESTABLISHMENT_MANAGER, SUPERADMIN}`.
- **Tokens carry a string `sub`.** `UserActor(user_id=payload["sub"], ...)`
  (`dependencies.py:86`) does no coercion, so `actor.user_id` is a `str`. Services
  must `UUID(str(actor.user_id))` before querying (the read service already does —
  `user_service.py:24`).

### Key discoveries / gotchas

- **Async expiry after `commit()`.** After a Core `UPDATE` + `commit()`, reading
  ORM attributes off the previously-loaded `User` can trigger an implicit refresh,
  which under async raises (the same class of footgun the read plan flagged for
  the lazy `establishments` relationship). **Capture every scalar field we need
  into locals _before_ writing/committing**, and build the response domain from
  those locals + the new values. Run only fresh queries (establishment assembly)
  after the commit.
- **`get_by_id` uses the identity map.** A Core `UPDATE` does not refresh the
  in-memory instance, so we never re-read the mutated row to build the response —
  we already know the new values.
- **Idempotent request semantics (decided for CA5/CA6).** Per establishment:
  `approved` → stays `approved` (untouched), `pending` → stays `pending`
  (untouched), `rejected` → set to `pending` (re-request), no existing relation →
  insert `pending`. No 409 conflict is raised; the response reports each requested
  establishment's resulting status. This satisfies CA6's "no duplicates / rejected
  may re-request" while being a clean idempotent upsert.
- **`?available=true` needs caller-scoped auth on a currently-public endpoint.**
  Availability is relative to the authenticated manager, so the catalog endpoint
  gains an **optional** bearer dependency: absent token → behaves as the public
  catalog; `available=true` requires a valid manager token (else 401/403). This is
  the one place a role check is conditional on a query param rather than a static
  dependency — documented as a deliberate, localized exception.

## Desired End State

- `PATCH /api/v1/users/me` with `{"name": "Juana"}` (any subset of
  `name`/`last_name`) returns `200` and the full updated profile; `{}` → `400`;
  `{"name": ""}` → `422`; `{"email": "x@y.z"}` (or `role`/`status`/any other key)
  → `422`; no/invalid token → `401`.
- `GET /api/v1/users/me/establishments` (manager) returns the caller's relations
  with status; non-manager → `403`; no token → `401`.
- `POST /api/v1/users/me/establishments` (manager) with
  `{"establishment_ids": [...]}` creates/updates relations to `pending`
  idempotently and returns the resulting status per establishment; unknown id →
  `404`; non-manager → `403`; no token → `401`.
- `GET /api/v1/establishments?available=true` (manager) returns the catalog minus
  the caller's `approved`/`pending` (rejected included); no token → `401`;
  non-manager → `403`. `GET /api/v1/establishments` (no flag) is unchanged and
  still public.

Verified by unit tests (services) + integration tests (real Postgres via
Testcontainers) and manual `curl`/Swagger checks.

## What We're NOT Doing

- No DB schema change, no Alembic migration.
- No changes to token issuance, login, or the centralized auth middleware/model.
- No editing of `email`, `role`, or `status` — explicitly rejected (CA3).
- No removing/cancelling existing relations, and no admin approve/reject changes
  (those are existing admin endpoints).
- No 409 conflict path for re-requests (superseded by the idempotent decision).
- `GET /api/v1/users/me/establishments` returns the caller's bounded relation set
  **unpaginated** (consistent with how the profile already returns it); the
  catalog/available listings stay paginated.

## Implementation Approach

Extend the existing `users` vertical slice and the establishments listing.
Add the two missing repository primitives (`UserRepository.update_profile`,
`EstablishmentRepository.get_available_for_user`); everything else reuses
existing repo methods. Put all new business logic in `UserService` (profile edit,
own relations, request access) and `EstablishmentService` (available listing).
Drive services with unit tests first (TDD), wire routes, then cover end-to-end
with integration tests. Refactor `get_profile` to share a `_build_profile` helper
so the PATCH response reuses the exact read assembly.

---

## Phase 1: Request/response schemas

### Overview

Add the PATCH request body and the access-request body. Reuse the existing
`ProfileResponse` and `EstablishmentWithStatusResponse`. No behavior yet.

### Changes Required

#### 1. Profile update + access-request schemas

**File**: `app/schemas/user_schema.py`
**Changes**: Add `ProfileUpdateRequest` (partial, `extra="forbid"`,
`min_length=1` names) and `EstablishmentAccessRequest` (non-empty id list). Keep
the existing response models.

```python
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ProfileUpdateRequest(BaseModel):
    """Editable profile fields. Any field other than these is rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = None
    last_name: (
        Annotated[str, StringConstraints(strict=True, min_length=1)] | None
    ) = None


class EstablishmentAccessRequest(BaseModel):
    """Establishment ids a manager wants to request access to."""

    establishment_ids: Annotated[list[UUID], Field(min_length=1)]
```

> `extra="forbid"` makes CA3 declarative: `email`/`role`/`status`/anything unknown
> → 422 naming the offending field. `min_length=1` makes CA2 (empty name) → 422.
> A defined-but-empty `{}` body passes Pydantic and is rejected by the service
> (`EmptyUpdateRequestError` → 400).

### Success Criteria

#### Automated Verification

- [x] Lint + format pass exactly as CI does: `poetry run pre-commit run --all-files`
- [x] Imports resolve: `poetry run python -c "from app.schemas.user_schema import ProfileUpdateRequest, EstablishmentAccessRequest"`

#### Manual Verification

- [x] `ProfileUpdateRequest(**{"email": "a@b.c"})` raises a validation error;
      `ProfileUpdateRequest()` is valid with both fields `None`;
      `ProfileUpdateRequest(name="")` raises.

---

## Phase 2: Repository methods (TDD)

### Overview

Add the two new persistence primitives. `update_profile` mirrors `update_status`;
`get_available_for_user` mirrors `get_paginated` with a `NOT IN (subquery)`
exclusion. Re-request/new-request reuse existing methods (no new association repo
method needed).

### Changes Required

#### 1. User profile update

**File**: `app/repositories/user_repository.py`
**Changes**: Add a Core-`UPDATE` method that sets only the provided columns.

```python
async def update_profile(self, user_id: UUID, values: dict[str, str]) -> None:
    """Update the given mutable profile columns for a user.

    ``values`` must contain only editable columns (name, last_name).
    """
    await self.db.execute(
        update(User).where(User.id == user_id).values(**values)
    )
```

#### 2. Establishments available to a manager

**File**: `app/repositories/establishment_repository.py`
**Changes**: Add a paginated query excluding establishments where the user already
has an `approved` or `pending` relation. Mirrors `get_paginated`.

```python
from app.domain.establishment import UserEstablishmentStatus
from app.models.user_establishment import UserEstablishment

async def get_available_for_user(
    self,
    user_id: UUID,
    limit: int,
    offset: int,
    search: str | None = None,
) -> tuple[list[Establishment], int]:
    """Return establishments the user can still request access to.

    Excludes establishments where the user already has an ``approved`` or
    ``pending`` relation. ``rejected`` relations are treated as available
    (re-requestable). ``search`` matches name or address (case-insensitive).
    """
    blocked = select(UserEstablishment.establishment_id).where(
        UserEstablishment.user_id == user_id,
        UserEstablishment.status.in_(
            [UserEstablishmentStatus.APPROVED, UserEstablishmentStatus.PENDING]
        ),
    )
    base_query = select(Establishment).where(Establishment.id.not_in(blocked))
    count_query = (
        select(func.count())
        .select_from(Establishment)
        .where(Establishment.id.not_in(blocked))
    )

    if search:
        search_term = f"%{escape_like(search)}%"
        condition = Establishment.name.ilike(
            search_term, escape="\\"
        ) | Establishment.address.ilike(search_term, escape="\\")
        base_query = base_query.where(condition)
        count_query = count_query.where(condition)

    return await execute_paginated(
        self.db, base_query, count_query, Establishment.created_at, limit, offset
    )
```

### Success Criteria

#### Automated Verification

- [x] Lint + format pass: `poetry run pre-commit run --all-files`
- [x] Imports resolve: `poetry run python -c "from app.repositories.user_repository import UserRepository; from app.repositories.establishment_repository import EstablishmentRepository"`
- [x] Repo behavior covered by the integration tests in Phase 5 (exclusion of
      approved/pending, inclusion of rejected) — exercised against real Postgres.

#### Manual Verification

- [x] No circular import introduced by importing `UserEstablishment` into the
      establishment repository.

---

## Phase 3: Service layer (TDD)

### Overview

All business logic. Write unit tests first (RED) using the AsyncMock `uow` pattern
from `tests/unit/test_user_service.py`, then implement (GREEN).

### Changes Required

#### 1. Unit tests (write first)

**File**: `tests/unit/test_user_service.py`
**Changes**: Add classes covering the three new `UserService` methods. Extend
`_make_uow` to stub `user_repo.update_profile`, `establishment_repo.get_all_by_ids`,
`user_establishment_repo.preset_relation`, `user_establishment_repo.update_status_for_ids`,
and `uow.commit` (AsyncMocks).

- **`update_profile`**
  - Both fields → builds values `{name, last_name}`, calls
    `user_repo.update_profile` with them, calls `commit`, returns a `ProfileDomain`
    carrying the new `name`/`last_name` and unchanged `email`/`role`/`status`.
  - Single field → values dict contains only that field.
  - Empty values dict (`{}`) → raises `EmptyUpdateRequestError`; `update_profile`
    repo + `commit` **not** called.
  - User id from token not found → raises `UserNotFoundError`.
  - Manager → returned `ProfileDomain.establishments` is the status-annotated list;
    non-manager → `None`.
  - `actor.user_id` passed as `str` → coerced to `UUID` (assert `get_by_id` called
    with a `UUID`).
- **`get_own_establishments`**
  - Manager with mixed-status relations → list of `EstablishmentWithStatusDomain`
    with correct status/name/address.
  - No relations → `[]`.
- **`request_establishment_access`**
  - New ids (no relation) → `preset_relation` called once per id; result all
    `pending`; `commit` called.
  - Rejected id → `update_status_for_ids(..., PENDING)` called; result `pending`.
  - Approved id → untouched (no preset, not in the update batch); result stays
    `approved`.
  - Pending id → untouched; result stays `pending`.
  - Mixed batch (approved + rejected + new) → exactly one `update_status_for_ids`
    for the rejected ids and one `preset_relation` per new id; approved untouched;
    result reflects each id's resulting status.
  - Duplicate ids in input → de-duplicated (no double insert).
  - Unknown establishment id → `get_all_by_ids` raises `EstablishmentNotFoundError`;
    nothing written, `commit` not called.

#### 2. Refactor `get_profile` + add the three methods

**File**: `app/services/user_service.py`
**Changes**: Extract `_build_profile(user)` and add the new methods. Read-before-commit
to dodge async expiry.

```python
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    UserNotFoundError,
)
from app.schemas.user_schema import ProfileUpdateRequest

# get_profile becomes:
async def get_profile(self, actor: UserActor) -> ProfileDomain:
    user_id = UUID(str(actor.user_id))
    user = await self.uow.user_repo.get_by_id(user_id)
    if user is None:
        raise UserNotFoundError(str(user_id))
    return await self._build_profile(user)

async def _build_profile(self, user) -> ProfileDomain:
    """Assemble a ProfileDomain from a loaded user (establishments only for
    managers). Read user scalars before any post-commit access."""
    establishments = None
    if user.role == UserRole.ESTABLISHMENT_MANAGER:
        establishments = await self._get_establishments_with_status(user.id)
    return ProfileDomain(
        id=user.id,
        email=user.email,
        name=user.name,
        last_name=user.last_name,
        role=user.role,
        status=user.status,
        establishments=establishments,
    )

async def update_profile(
    self, actor: UserActor, data: ProfileUpdateRequest
) -> ProfileDomain:
    """Update the caller's editable profile fields and return the new profile.

    Raises:
        UserNotFoundError: If the token's user no longer exists.
        EmptyUpdateRequestError: If no editable field was provided.
    """
    user_id = UUID(str(actor.user_id))
    user = await self.uow.user_repo.get_by_id(user_id)
    if user is None:
        raise UserNotFoundError(str(user_id))

    values = data.model_dump(exclude_unset=True, exclude_none=True)
    if not values:
        raise EmptyUpdateRequestError()

    # Capture scalars BEFORE the write/commit to avoid async attribute expiry.
    email, role, status = user.email, user.role, user.status
    name = values.get("name", user.name)
    last_name = values.get("last_name", user.last_name)

    await self.uow.user_repo.update_profile(user_id, values)
    await self.uow.commit()

    establishments = None
    if role == UserRole.ESTABLISHMENT_MANAGER:
        establishments = await self._get_establishments_with_status(user_id)

    return ProfileDomain(
        id=user_id,
        email=email,
        name=name,
        last_name=last_name,
        role=role,
        status=status,
        establishments=establishments,
    )

async def get_own_establishments(
    self, actor: UserActor
) -> list[EstablishmentWithStatusDomain]:
    """Return the caller's establishment relations, each with its status."""
    user_id = UUID(str(actor.user_id))
    return await self._get_establishments_with_status(user_id)

async def request_establishment_access(
    self, actor: UserActor, establishment_ids: list[UUID]
) -> list[EstablishmentWithStatusDomain]:
    """Request (or re-request) access to establishments. Idempotent per item:
    approved/pending stay as-is, rejected/new become pending.

    Raises:
        EstablishmentNotFoundError: If any establishment id does not exist.
    """
    user_id = UUID(str(actor.user_id))
    unique_ids = list(dict.fromkeys(establishment_ids))  # dedupe, keep order

    establishments = await self.uow.establishment_repo.get_all_by_ids(unique_ids)
    info = {e.id: (e.name, e.address) for e in establishments}  # before commit

    relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
    status_by_estab = {rel.establishment_id: rel.status for rel in relations}

    to_repend: list[UUID] = []
    to_insert: list[UUID] = []
    result_status: dict[UUID, UserEstablishmentStatus] = {}
    for estab_id in unique_ids:
        current = status_by_estab.get(estab_id)
        if current in (
            UserEstablishmentStatus.APPROVED,
            UserEstablishmentStatus.PENDING,
        ):
            result_status[estab_id] = current
        elif current == UserEstablishmentStatus.REJECTED:
            to_repend.append(estab_id)
            result_status[estab_id] = UserEstablishmentStatus.PENDING
        else:
            to_insert.append(estab_id)
            result_status[estab_id] = UserEstablishmentStatus.PENDING

    if to_repend:
        await self.uow.user_establishment_repo.update_status_for_ids(
            user_id, to_repend, UserEstablishmentStatus.PENDING
        )
    for estab_id in to_insert:
        await self.uow.user_establishment_repo.preset_relation(user_id, estab_id)
    await self.uow.commit()

    return [
        EstablishmentWithStatusDomain(
            id=estab_id,
            name=info[estab_id][0],
            address=info[estab_id][1],
            status=result_status[estab_id],
        )
        for estab_id in unique_ids
    ]
```

#### 3. Available-establishments service method

**File**: `app/services/establishment_service.py`
**Changes**: Add a method paralleling `get_establishments_paginated`, scoped to a
user via the new repo method.

```python
from uuid import UUID

async def get_available_establishments(
    self,
    user_id: UUID,
    page: int,
    page_size: int,
    search: str | None,
) -> PaginatedResult[EstablishmentDomain]:
    """Return establishments the user can still request, paginated."""
    offset = (page - 1) * page_size
    search = search.strip() or None if search else None
    establishments, total = await self.uow.establishment_repo.get_available_for_user(
        user_id=user_id, limit=page_size, offset=offset, search=search
    )
    return PaginatedResult.build(
        items=[
            EstablishmentDomain(
                id=establishment.id,
                name=establishment.name,
                address=establishment.address,
            )
            for establishment in establishments
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
```

#### 4. Establishment-service unit tests

**File**: `tests/unit/test_establishment_service.py`
**Changes**: Add a test for `get_available_establishments` stubbing
`establishment_repo.get_available_for_user` → asserts offset math, search
stripping, and `EstablishmentDomain` mapping (mirror existing
`get_establishments_paginated` tests).

### Success Criteria

#### Automated Verification

- [x] New unit tests pass: `poetry run pytest tests/unit/test_user_service.py tests/unit/test_establishment_service.py`
- [x] No regressions in the unit suite: `poetry run pytest tests/unit/`
- [x] Lint + format pass: `poetry run pre-commit run --all-files`

#### Manual Verification

- [x] `update_profile` and `request_establishment_access` never read mutated ORM
      scalars after `commit()` (all response values captured beforehand or via a
      fresh query).

---

## Phase 4: Dependencies + routes

### Overview

Add the optional-auth dependency, the three `users` routes, and the `available`
branch on the establishments route. Routers are already mounted
(`app/api/v1/router.py:11`, `:9`).

### Changes Required

#### 1. Optional-auth dependency

**File**: `app/core/dependencies.py`
**Changes**: Add a bearer scheme with `auto_error=False` and a dependency that
yields `UserActor | None` (None when no token; raises 401 on a present-but-invalid
token).

```python
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)


async def get_optional_actor(
    token: str | None = Depends(oauth2_scheme_optional),
) -> UserActor | None:
    """Return the authenticated actor, or None when no token is supplied.

    A present-but-invalid token still raises UnauthorizedError.
    """
    if not token:
        return None
    payload = _decode_verified_payload(token)
    return UserActor(user_id=payload["sub"], role=payload["role"])
```

#### 2. `users` routes

**File**: `app/api/v1/users.py`
**Changes**: Add `PATCH /me`, `GET /me/establishments`, `POST /me/establishments`
alongside the existing `GET /me`.

```python
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_manager, get_user_service, require_any
from app.domain.user import UserActor
from app.schemas.user_schema import (
    EstablishmentAccessRequest,
    EstablishmentWithStatusResponse,
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.services.user_service import UserService

# GET /me unchanged …

@router.patch(
    "/me",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit own profile",
    description="Updates the authenticated user's editable fields (name, "
    "last_name). Other fields (email, role, status) are rejected.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "No editable field provided"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_404_NOT_FOUND: {"description": "Authenticated user no longer exists"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Invalid value or attempt to edit a non-editable field"
        },
    },
)
async def update_my_profile(
    data: ProfileUpdateRequest,
    actor: UserActor = Depends(require_any),
    service: UserService = Depends(get_user_service),
) -> ProfileResponse:
    profile = await service.update_profile(actor, data)
    return ProfileResponse.model_validate(profile)


@router.get(
    "/me/establishments",
    response_model=list[EstablishmentWithStatusResponse],
    status_code=status.HTTP_200_OK,
    summary="List own establishment relations",
    description="Returns the manager's establishments, each with its approval "
    "status. Manager only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Caller is not a manager"},
    },
)
async def list_my_establishments(
    actor: UserActor = Depends(get_current_manager),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.get_own_establishments(actor)
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]


@router.post(
    "/me/establishments",
    response_model=list[EstablishmentWithStatusResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Request establishment access",
    description="Requests access to one or more establishments. Idempotent: "
    "already-approved/pending stay unchanged, rejected ones are re-requested "
    "(set to pending). Manager only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Caller is not a manager"},
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def request_establishment_access(
    data: EstablishmentAccessRequest,
    actor: UserActor = Depends(get_current_manager),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.request_establishment_access(
        actor, data.establishment_ids
    )
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]
```

#### 3. `available=true` on the establishments route

**File**: `app/api/v1/establishments.py`
**Changes**: Add the `available` query flag and the optional actor. When
`available` is set, require a manager (401 if unauthenticated, 403 if not a
manager) and serve the user-scoped list; otherwise keep the public catalog path.

```python
from uuid import UUID

from app.core.dependencies import get_establishment_service, get_optional_actor
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError, UnauthorizedError

_MANAGER_ROLES = {UserRole.ESTABLISHMENT_MANAGER, UserRole.SUPERADMIN}

async def get_establishments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    available: bool = Query(
        default=False,
        description="If true, return only establishments the authenticated "
        "manager can still request (excludes approved/pending). Requires a "
        "manager token.",
    ),
    actor: UserActor | None = Depends(get_optional_actor),
    service: EstablishmentService = Depends(get_establishment_service),
) -> PaginatedResponse[EstablishmentResponse]:
    if available:
        if actor is None:
            raise UnauthorizedError()
        if actor.role not in _MANAGER_ROLES:
            raise ForbiddenError()
        result = await service.get_available_establishments(
            user_id=UUID(str(actor.user_id)),
            page=page,
            page_size=page_size,
            search=search,
        )
    else:
        result = await service.get_establishments_paginated(
            page=page, page_size=page_size, search=search
        )

    return PaginatedResponse[EstablishmentResponse](
        items=[EstablishmentResponse.model_validate(e) for e in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
```

> Architecture note: per `CLAUDE.md`, per-establishment permission checks are
> centralized in middleware and never inline. That rule governs **resource
> ownership** checks; the inline `available`/role gate here is **role
> authorization** (the same kind `get_current_manager` does), made conditional on a
> query param — which a static dependency cannot express. The data logic stays in
> the service.

### Success Criteria

#### Automated Verification

- [x] App imports and routes register:
      `poetry run python -c "from app.main import app; paths={getattr(r,'path',None) for r in app.routes}; assert {'/api/v1/users/me','/api/v1/users/me/establishments'} <= paths"`
- [x] Lint + format pass: `poetry run pre-commit run --all-files`

#### Manual Verification

- [ ] Swagger (`/docs`) shows `PATCH /users/me`, `GET`+`POST /users/me/establishments`
      under "Users V1" and the `available` param on `GET /establishments`.
- [ ] `GET /establishments` with no token still returns the public catalog.

---

## Phase 5: Integration tests

### Overview

End-to-end HTTP tests against real Postgres (Testcontainers, Docker required),
reusing the seeding helpers in `tests/integration/test_users.py`
(`_insert_user`, `_insert_establishment`, `_insert_relation`, `_headers_for`) and
the `clean_db` truncation fixture (`tests/integration/conftest.py:69`).

### Changes Required

#### 1. Profile edit tests

**File**: `tests/integration/test_users.py`
**Changes**: New class covering `PATCH /me`.

- **CA1** professional edits `name`+`last_name` → 200, body reflects new values;
  re-`GET /me` confirms persistence.
- **CA1 partial** → send only `name` → 200, `last_name` unchanged.
- **CA2** `{"name": ""}` → 422; DB unchanged.
- **CA2** empty body `{}` → 400 (`EmptyUpdateRequestError`).
- **CA3** `{"email": "x@y.z"}`, `{"role": "admin"}`, `{"status": "active"}` → 422
  each; DB unchanged.
- **CA1 manager** edits name → 200 and the response still includes the manager's
  `establishments` with statuses (proves `_build_profile` reuse).
- **CA7** no token / malformed token → 401.

#### 2. Own-relations + request-access tests

**File**: `tests/integration/test_users.py`
**Changes**: New classes covering `GET`/`POST /me/establishments`.

- **GET own** manager with seeded mixed-status relations → 200 list with correct
  statuses; non-manager (professional) → 403; no token → 401.
- **CA5 new** manager POSTs new establishment ids → 201, all `pending`; DB rows
  created `pending`.
- **CA5/CA6 rejected re-request** seed a `rejected` relation, POST that id → 201,
  result `pending`, DB row flipped to `pending`.
- **CA6 approved stays** seed `approved`, POST a batch `[approved_id, new_id]` →
  201; approved row untouched (`approved`), new row `pending`; no duplicate rows.
- **CA6 pending stays** seed `pending`, POST that id again → 201, still single
  `pending` row.
- **invalid establishment** POST an unknown id → 404; no rows written.
- **CA7** non-manager → 403; no token → 401.

#### 3. Available-catalog tests

**File**: `tests/integration/test_establishment.py`
**Changes**: New class covering `GET /establishments?available=true`.

- Seed manager + establishments A (approved), B (pending), C (rejected), D (no
  relation). `available=true` → returns C and D only (A, B excluded; C included).
- `available=true` with `search` narrows by name/address.
- `available=true` no token → 401; professional token → 403.
- `GET /establishments` (no flag, no token) → unchanged public catalog (regression).

### Success Criteria

#### Automated Verification

- [x] New integration tests pass (Docker running): `poetry run pytest tests/integration/test_users.py tests/integration/test_establishment.py` (47 passed)
- [x] Migration round-trip unaffected (no schema change): no migration/model files added; the integration `app` fixture runs `alembic upgrade head` against Testcontainer Postgres before every run and the suite passed. (Standalone `alembic check` needs a local Postgres on :5432, which is not running here.)
- [x] Full suite green: `poetry run pytest` (382 passed)
- [x] Coverage holds ≥80%: `poetry run pytest --cov=app --cov-report=term-missing` (93% total; user/establishment services 100%)
- [x] Lint + format pass: `poetry run pre-commit run --all-files`

#### Manual Verification

- [ ] `curl -X PATCH -H "Authorization: Bearer <token>" -d '{"name":"Juana"}' localhost:8080/api/v1/users/me` returns the updated profile.
- [ ] `curl -X POST -H "Authorization: Bearer <manager>" -d '{"establishment_ids":["<id>"]}' .../users/me/establishments` returns the id as `pending`.
- [ ] `GET /establishments?available=true` with a manager token omits already-approved/pending establishments.

---

## Testing Strategy

### Unit (TDD, Phase 3)

- `UserService.update_profile` / `get_own_establishments` /
  `request_establishment_access` and `EstablishmentService.get_available_establishments`
  driven by AsyncMock `uow`. Assert role branching, idempotent classification
  (approved/pending/rejected/new), dedupe, str→UUID coercion, the empty-update and
  not-found error paths, and that nothing is written when validation fails.

### Integration (Phase 5)

- Real Postgres via Testcontainers; seed rows directly and assert response shapes
  + persisted state per AC, plus 401/403/404/422 paths.

### Manual

1. `poetry run uvicorn app.main:app --reload`.
2. Log in as a professional and a manager (`/api/v1/auth/login`).
3. `PATCH /users/me` (valid, empty, invalid, forbidden-field).
4. `GET /establishments?available=true`, then `POST /users/me/establishments` with
   a selection, then `GET /users/me/establishments` and `GET /users/me` to confirm.

## Performance Considerations

- `PATCH /me`: one `SELECT`, one `UPDATE`, plus (managers only) the two-query
  establishment assembly. No N+1.
- `POST /me/establishments`: `get_all_by_ids` (one query), `get_by_user_id` (one
  query), one batched `update_status_for_ids`, and N inserts for genuinely new ids
  (bounded by request size). Establishment name/address read from a pre-commit
  snapshot — no per-item query.
- `GET /establishments?available=true`: a single paginated query with a correlated
  `NOT IN` subquery over `user_establishments` (keyed by `user_id`). Establishment
  catalog and a manager's relation set are both small/bounded.

## Migration Notes

None — no schema change. `users.name`/`last_name`, `establishments`, and
`user_establishments` (with `status`) already exist.

## References

- Read-side plan & template: `docs/plans/visualizacion_de_perfil_propio.md`
- Read endpoint: `app/api/v1/users.py`, `app/services/user_service.py:15-68`
- Write template (create + preset + commit): `app/services/auth_service.py:54-66`
- Status update template: `app/services/admin_service.py:155-196`,
  `app/repositories/user_establishment_repository.py:46-60`
- Existence validation: `app/repositories/establishment_repository.py:29-44`
- Listing/pagination: `app/repositories/establishment_repository.py:46-69`,
  `app/services/establishment_service.py`, `app/api/v1/establishments.py`
- Error mapping: `app/exceptions/exception_handlers.py`,
  `app/exceptions/domain_exceptions.py:156-163`
- Auth dependencies: `app/core/dependencies.py:89-130`
- Conventions: `docs/conventions.md`, `docs/architecture.md`, `docs/auth.md`
</content>
</invoke>
