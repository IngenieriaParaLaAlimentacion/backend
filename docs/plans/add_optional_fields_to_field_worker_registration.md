# Add Optional Fields to Field Worker Registration and Profile Edit

## Overview

Add `locality`, `description`, and `contact_phone` as optional fields to two flows:

1. **Field worker registration** (`POST /api/v2/auth/register/field-worker`)
2. **Profile self-edit** (`PATCH /api/v1/users/me`)

The `RegisterFieldWorkerRequest` schema already declares the three fields but without
a default value, which is a Pydantic v2 bug fixed in Phase 1.

## Current State Analysis

### Registration flow

The schema declares the fields but without `= None`:

```python
# app/schemas/auth_schema.py:14-16
locality: TextStr | None
description: TextStr | None
contact_phone: TextStr | None
```

In Pydantic v2, `T | None` without a default means the field is **required** — the client
must send it (even as `null`). This silently breaks the existing unit fixture
(`valid_register_request`) and the integration helper (`_register`) that do not supply
these fields. The plan fixes this as part of Phase 1.

The rest of the registration stack is missing the fields:

| File | Gap |
|---|---|
| `app/models/user.py` | No `locality`, `description`, `contact_phone` columns |
| `app/domain/user.py` | `BaseUserDomain` has no optional fields for them |
| `app/schemas/auth_schema.py:26-35` | `RegistrationResponse` does not return them |
| `app/repositories/user_repository.py:16-31` | `create()` ignores them |
| `app/services/auth_service.py:58-80` | `register_field_worker()` does not pass or return them |
| `tests/unit/test_auth_service.py:188-194` | `assert_called_once_with` will diverge after service change |

### Profile edit flow

| File | Gap |
|---|---|
| `app/schemas/user_schema.py:32-40` | `ProfileUpdateRequest` only allows `name` and `last_name` |
| `app/schemas/user_schema.py:21-29` | `ProfileResponse` does not include the three fields |
| `app/services/user_service.py:47-63` | `_build_profile()` does not pass them to `ProfileDomain` |
| `app/services/user_service.py:102-137` | `update_profile()` does not capture or return them |
| `app/api/v1/users.py:49-50` | Endpoint description lists only `name, last_name` |

## Desired End State

- `POST /api/v2/auth/register/field-worker` accepts the three fields as optional,
  persists them, and echoes them in the response.
- `PATCH /api/v1/users/me` accepts the three new fields as optional editable columns
  (alongside the existing `name` and `last_name`).
- `GET /api/v1/users/me` returns the three fields in the profile response.
- `BaseUserDomain` carries the three fields so both response paths share the same domain.

### Key Discoveries

- `BaseUserDomain` (`app/domain/user.py:34-42`) is the shared base for `UserDomain`,
  `UserWithEstablishmentsDomain`, and `ProfileDomain`. Adding optional fields there
  propagates to all user responses without further changes.
- `user_service.update_profile()` uses `model_dump(exclude_unset=True, exclude_none=True)`,
  so only explicitly-provided fields are written to the DB. The repository's generic
  `values(**values)` (`app/repositories/user_repository.py:113-114`) means no repository
  change is needed for the edit flow — only schema and service.
- `update_profile()` captures `name` and `last_name` scalars before the commit to avoid
  async ORM attribute expiry (`app/services/user_service.py:119-120`). The same pattern
  must be applied for the three new fields.
- `_make_user()` in `tests/unit/test_user_service.py:20-32` uses `MagicMock()` and
  does not set the new attributes explicitly — needs `locality = None`,
  `description = None`, `contact_phone = None` added for correctness.

## What We're NOT Doing

- Exposing these fields on the admin user management endpoints.
- Forcing `contact_phone` to be purely numeric (international formats use `+`, `-`, spaces).
- Adding search/filter by `locality`.
- Touching any other registration path (analyst invite, admin creation).

## Validation Decisions

| Field | Constraints |
|---|---|
| `locality` | `min_length=1`, `max_length=100` |
| `description` | `min_length=1`, `max_length=500` |
| `contact_phone` | `min_length=1`, `max_length=20`, regex `^[0-9+\-\s()]+$` (digits, `+`, `-`, spaces, parentheses) |

The same constraints apply in both `RegisterFieldWorkerRequest` and `ProfileUpdateRequest`.
No DB-level length constraints — application validation is the single source of truth.

## Implementation Approach

Natural layer order for a schema change:

1. Fix the schema default (unblocks existing tests immediately).
2. Add ORM columns.
3. Generate and review the Alembic migration.
4. Propagate through domain and both response/request schemas.
5. Update repository (`create`) and both services (`auth_service`, `user_service`).
6. Update endpoint description string.
7. Fix unit tests and add new coverage.

---

## Phase 1: Fix Schema Default

### Overview

Make the three fields truly optional in `RegisterFieldWorkerRequest` by adding `= None`.
In Pydantic v2, `T | None` without a default makes the field required. Without this fix
the endpoint rejects any request that omits the fields, even though the intent is optional.

### Changes Required

#### `app/schemas/auth_schema.py`

Replace the three existing field declarations with:

```python
locality: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)] | None = None
description: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)] | None = None
contact_phone: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=20, pattern=r"^[0-9+\-\s()]+$")] | None = None
```

`StringConstraints` is already imported via `from pydantic import ..., StringConstraints`.

### Success Criteria

#### Automated Verification

- [ ] `poetry run ruff check . --fix && poetry run ruff format .` — no errors
- [ ] `poetry run pytest tests/unit/` — existing tests still pass

---

## Phase 2: ORM Model

### Overview

Add the three nullable columns to the `User` ORM model so SQLAlchemy can generate the
migration and persist the values.

### Changes Required

#### `app/models/user.py`

Add after `updated_at`:

```python
locality = Column(String, nullable=True)
description = Column(String, nullable=True)
contact_phone = Column(String, nullable=True)
```

### Success Criteria

#### Automated Verification

- [ ] `poetry run ruff check . --fix && poetry run ruff format .` — no errors

---

## Phase 3: Alembic Migration

### Overview

Generate and review the autogenerated migration that adds the three columns.

### Steps

```bash
poetry run alembic revision --autogenerate \
  -m "add_locality_description_contact_phone_to_users"
```

Review the generated file in `alembic/versions/` and confirm it contains:

```python
def upgrade() -> None:
    op.add_column("users", sa.Column("locality", sa.String(), nullable=True))
    op.add_column("users", sa.Column("description", sa.String(), nullable=True))
    op.add_column("users", sa.Column("contact_phone", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("users", "contact_phone")
    op.drop_column("users", "description")
    op.drop_column("users", "locality")
```

### Success Criteria

#### Automated Verification

- [ ] Migration applies cleanly: `poetry run alembic upgrade head`
- [ ] Migration round-trips: `poetry run alembic downgrade -1 && poetry run alembic upgrade head`

---

## Phase 4: Domain and Schemas

### Overview

Add the three optional fields to `BaseUserDomain` (inherited by all user domain types),
`RegistrationResponse`, `ProfileResponse`, and `ProfileUpdateRequest`.

### Changes Required

#### `app/domain/user.py` — `BaseUserDomain`

Dataclass fields with defaults must come after fields without defaults. Add the three
new optional fields at the end:

```python
@dataclass
class BaseUserDomain:
    """Shared fields for all user domain representations."""

    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None
```

#### `app/schemas/auth_schema.py` — `RegistrationResponse`

```python
class RegistrationResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    establishments: list[UUID]
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None

    model_config = {"from_attributes": True}
```

#### `app/schemas/user_schema.py` — `ProfileResponse`

```python
class ProfileResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    establishments: list[EstablishmentWithStatusResponse] | None = None
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None

    model_config = {"from_attributes": True}
```

#### `app/schemas/user_schema.py` — `ProfileUpdateRequest`

Same constraints as `RegisterFieldWorkerRequest` — same validation rules, same UX:

```python
class ProfileUpdateRequest(BaseModel):
    """Editable profile fields. Any field other than these is rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = None
    last_name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = None
    locality: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)] | None = None
    description: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)] | None = None
    contact_phone: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=20, pattern=r"^[0-9+\-\s()]+$")] | None = None
```

### Success Criteria

#### Automated Verification

- [ ] `poetry run ruff check . --fix && poetry run ruff format .` — no errors
- [ ] `poetry run pytest tests/unit/` — no regressions

---

## Phase 5: Repository and Services

### Overview

Wire the three fields in the registration path (repository + `auth_service`) and in the
profile edit/read path (`user_service`).

### Changes Required

#### `app/repositories/user_repository.py` — `create()`

```python
async def create(
    self,
    email: str,
    name: str,
    last_name: str,
    role: str = UserRole.FIELD_WORKER,
    status: UserStatus = UserStatus.PENDING_VALIDATION,
    locality: str | None = None,
    description: str | None = None,
    contact_phone: str | None = None,
) -> User:
    """Persist a new user. Password and establishments are handled separately."""
    user = User(
        email=email,
        name=name,
        last_name=last_name,
        role=role,
        status=status,
        locality=locality,
        description=description,
        contact_phone=contact_phone,
    )
    self.db.add(user)
    await self.db.flush()
    await self.db.refresh(user)
    return user
```

#### `app/services/auth_service.py` — `register_field_worker()`

Pass the new fields to `user_repo.create()`:

```python
user = await self.uow.user_repo.create(
    email=data.email,
    name=data.name,
    last_name=data.last_name,
    role=UserRole.FIELD_WORKER,
    status=UserStatus.PENDING_VALIDATION,
    locality=data.locality,
    description=data.description,
    contact_phone=data.contact_phone,
)
```

Include them in the returned `UserDomain`:

```python
return UserDomain(
    id=user.id,
    email=str(user.email),
    name=user.name,
    last_name=user.last_name,
    role=user.role,
    status=user.status,
    establishments=[establishment.id for establishment in establishments],
    locality=user.locality,
    description=user.description,
    contact_phone=user.contact_phone,
)
```

#### `app/services/user_service.py` — `_build_profile()`

```python
return ProfileDomain(
    id=user.id,
    email=user.email,
    name=user.name,
    last_name=user.last_name,
    role=user.role,
    status=user.status,
    establishments=establishments,
    locality=user.locality,
    description=user.description,
    contact_phone=user.contact_phone,
)
```

#### `app/services/user_service.py` — `update_profile()`

Capture the three new scalars before the write (same pattern as `name`/`last_name`),
and include them in the returned `ProfileDomain`:

```python
# Capture scalars before the write/commit to avoid async attribute expiry.
email, role, status = user.email, user.role, user.status
name = values.get("name", user.name)
last_name = values.get("last_name", user.last_name)
locality = values.get("locality", user.locality)
description = values.get("description", user.description)
contact_phone = values.get("contact_phone", user.contact_phone)

await self.uow.user_repo.update_profile(user.id, values)
await self.uow.commit()

...

return ProfileDomain(
    id=user.id,
    email=email,
    name=name,
    last_name=last_name,
    role=role,
    status=status,
    establishments=establishments,
    locality=locality,
    description=description,
    contact_phone=contact_phone,
)
```

#### `app/api/v1/users.py` — endpoint description

Update the `PATCH /me` description string from:

```python
description="Updates the authenticated user's editable fields (name, "
"last_name). Other fields (email, role, status) are rejected.",
```

to:

```python
description="Updates the authenticated user's editable fields (name, last_name, "
"locality, description, contact_phone). Other fields (email, role, status) are rejected.",
```

### Success Criteria

#### Automated Verification

- [ ] `poetry run ruff check . --fix && poetry run ruff format .` — no errors
- [ ] `poetry run pytest tests/unit/` — all pass (test assertion fix in Phase 6)

---

## Phase 6: Tests

### Overview

Fix the one diverged unit test assertion, update the `_make_user` fixture for
correctness, and add targeted coverage for both flows.

### Changes Required

#### `tests/unit/test_user_service.py` — `_make_user()` fixture

Add explicit `None` values to avoid relying on `MagicMock` auto-attribute behavior:

```python
def _make_user(*, role=UserRole.FIELD_WORKER, status=UserStatus.ACTIVE):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    user.name = "Test"
    user.last_name = "User"
    user.role = role
    user.status = status
    user.locality = None
    user.description = None
    user.contact_phone = None
    return user
```

#### `tests/unit/test_auth_service.py` — fix diverged assertion

`test_creates_field_worker_with_correct_role_and_status` (line 188):

```python
uow.user_repo.create.assert_called_once_with(
    email=valid_register_request.email,
    name=valid_register_request.name,
    last_name=valid_register_request.last_name,
    role=UserRole.FIELD_WORKER,
    status=UserStatus.PENDING_VALIDATION,
    locality=None,
    description=None,
    contact_phone=None,
)
```

#### `tests/unit/test_auth_service.py` — new test for populated optional fields

Add inside `TestRegisterFieldWorker`:

```python
@pytest.mark.asyncio
async def test_passes_optional_fields_to_repository(
    self, make_uow, make_establishment
):
    establishment = make_establishment()
    uow = make_uow(establishments=[establishment])
    request = RegisterFieldWorkerRequest(
        email="worker@example.com",
        password="securepassword",
        name="Juan",
        last_name="Perez",
        establishments=[establishment.id],
        locality="Villa Lugano",
        description="Community health promoter",
        contact_phone="1134567890",
    )

    await AuthService(uow).register_field_worker(request)

    uow.user_repo.create.assert_called_once_with(
        email=request.email,
        name=request.name,
        last_name=request.last_name,
        role=UserRole.FIELD_WORKER,
        status=UserStatus.PENDING_VALIDATION,
        locality="Villa Lugano",
        description="Community health promoter",
        contact_phone="1134567890",
    )
```

#### `tests/unit/test_user_service.py` — new tests for profile edit

Add inside `TestUpdateProfile`:

```python
@pytest.mark.asyncio
async def test_new_optional_fields_are_written_and_returned(self):
    user = _make_user(role=UserRole.FIELD_WORKER)
    uow = _make_uow(user=user)
    service = UserService(uow)

    data = ProfileUpdateRequest(locality="Villa Lugano", contact_phone="1134567890")
    profile = await service.update_profile(_actor_for(user), data)

    _, values = uow.user_repo.update_profile.call_args.args
    assert values == {"locality": "Villa Lugano", "contact_phone": "1134567890"}
    assert profile.locality == "Villa Lugano"
    assert profile.contact_phone == "1134567890"
    assert profile.description is None  # not sent, falls back to user.description

@pytest.mark.asyncio
async def test_unset_optional_fields_fall_back_to_existing_values(self):
    user = _make_user(role=UserRole.ANALYST)
    user.locality = "Existing locality"
    uow = _make_uow(user=user)
    service = UserService(uow)

    data = ProfileUpdateRequest(name="New Name")
    profile = await service.update_profile(_actor_for(user), data)

    assert profile.locality == "Existing locality"
```

#### `tests/integration/test_auth.py` — validation tests for new constraints

Add inside `TestRegisterFieldWorker`:

```python
async def test_invalid_phone_format_returns_422(self, client, db_establishment):
    response = await self._register(
        client,
        establishments=[str(db_establishment.id)],
        contact_phone="not-a-phone!!",
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

async def test_description_exceeding_max_length_returns_422(self, client, db_establishment):
    response = await self._register(
        client,
        establishments=[str(db_establishment.id)],
        description="x" * 501,
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

async def test_locality_exceeding_max_length_returns_422(self, client, db_establishment):
    response = await self._register(
        client,
        establishments=[str(db_establishment.id)],
        locality="x" * 101,
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
```

#### `tests/integration/test_auth.py` — new tests for registration

Add inside `TestRegisterFieldWorker`:

```python
async def test_optional_fields_are_returned_in_response(
    self, client, db_establishment
):
    response = await self._register(
        client,
        establishments=[str(db_establishment.id)],
        locality="Villa Lugano",
        description="Community health promoter",
        contact_phone="1134567890",
    )
    data = response.json()
    assert data["locality"] == "Villa Lugano"
    assert data["description"] == "Community health promoter"
    assert data["contact_phone"] == "1134567890"

async def test_optional_fields_default_to_null(self, client, db_establishment):
    response = await self._register(
        client, establishments=[str(db_establishment.id)]
    )
    data = response.json()
    assert data["locality"] is None
    assert data["description"] is None
    assert data["contact_phone"] is None
```

### Success Criteria

#### Automated Verification

- [ ] `poetry run pre-commit run --all-files` — lint and format pass
- [ ] `poetry run pytest tests/unit/` — all pass including new tests
- [ ] `poetry run pytest` (Docker required) — full suite passes including new integration tests

#### Manual Verification

- [ ] `POST /api/v2/auth/register/field-worker` with all three fields returns them in the
  response body.
- [ ] Same endpoint without the three fields returns `"locality": null`,
  `"description": null`, `"contact_phone": null`.
- [ ] `PATCH /api/v1/users/me` with `{"locality": "Villa Lugano"}` returns the updated
  `locality` in the response and leaves `description` and `contact_phone` unchanged.
- [ ] `GET /api/v1/users/me` returns the three fields.
- [ ] `PATCH /api/v1/users/me` with `{"email": "x@x.com"}` still returns 422.
- [ ] `poetry run alembic downgrade -1` drops the three columns cleanly and
  `alembic upgrade head` re-adds them.

---

## Testing Strategy

### Unit Tests (`tests/unit/`)

- Corrected assertion in `test_creates_field_worker_with_correct_role_and_status` — `None`-default path in registration.
- New `test_passes_optional_fields_to_repository` — populated values path in registration.
- New `test_new_optional_fields_are_written_and_returned` — populated values path in profile edit.
- New `test_unset_optional_fields_fall_back_to_existing_values` — fallback behavior in profile edit.

### Integration Tests (`tests/integration/`)

- `test_optional_fields_are_returned_in_response` — full round-trip registration with values.
- `test_optional_fields_default_to_null` — full round-trip registration without the fields.

---

## Performance Considerations

No performance impact. Three nullable `VARCHAR` columns, no indexes required, no
additional queries in any path.

---

## Migration Notes

- All three columns are `nullable=True` → no backfill needed.
- `downgrade` simply drops the columns; data in those columns is lost on downgrade.
- Alembic autogenerate is reliable for simple column additions — verify the generated
  file matches the template in Phase 3 before applying.

---

## References

- Registration service: `app/services/auth_service.py` `register_field_worker()`
- Profile edit service: `app/services/user_service.py` `update_profile()` and `_build_profile()`
- Domain base: `app/domain/user.py:34` `BaseUserDomain`
- Conventions: `docs/conventions.md`, `docs/architecture.md`
