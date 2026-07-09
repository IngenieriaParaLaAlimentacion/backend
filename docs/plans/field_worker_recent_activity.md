# Field Worker Recent Activity Implementation Plan

## Overview

Expose `GET /api/v1/users/me/activity`, a self-scoped, paginated feed of the
current user's own "publishing" actions — subjects they registered and
measurements they recorded — merged into a single list ordered by date
(most recent first). This is the backend support for a mobile "recent
activity" screen for field workers.

## Current State Analysis

- **No activity/history endpoint exists.** `app/api/v1/router.py` mounts
  `admin`, `auth`, `establishments`, `subjects`, `measurements`, `users`.
  `app/api/v1/users.py` already establishes a `/users/me/*` convention
  (`GET /users/me`, `PATCH /users/me`, `GET /users/me/establishments`,
  `POST /users/me/establishments`) — the new route follows it.
- **`Subject` has no creator field.** Authorship only exists in the
  append-only `subject_events` audit log
  (`app/models/subject_event.py`): `actor_id` + `event_type`. A
  `SUBJECT_CREATED` event is appended in the same transaction as the
  insert (`app/services/subject_service.py:78-82`), so
  `subject_events.occurred_at` and `subjects.created_at` are effectively
  identical.
- **`Measurement` carries authorship directly**: `responsible_id`
  (`app/models/measurement.py:21-23`), always set to the uploading user's
  id (`app/services/measurement_service.py:85`, `responsible_id=actor.user_id`).
  No coercion happens there today (bind-param coercion handles it), but
  see the gotcha below for why we coerce explicitly in the new service.
- **`GET /measurements` is admin/analyst only**
  (`app/api/v1/measurements.py:82`, `require_admin_or_analyst`) — field
  workers cannot call it today. **`GET /subjects` is open to all roles**
  (`app/api/v1/subjects.py:103`, `require_any`) but has no creator filter.
  Neither endpoint is reused; this plan adds a new, purpose-built,
  self-scoped endpoint instead of loosening `/measurements`'s permissions
  or bolting a creator filter onto `/subjects`.
- **Per-establishment permission middleware does not apply here.** Per
  `docs/auth.md`, that check only fires when a request references an
  `establishment_id`. `GET /users/me/activity` has none — it's scoped by
  `user_id`, and a field worker's own subjects/measurements are already
  establishment-scoped at creation time
  (`app/services/measurement_service.py:44-53`,
  `_check_establishment_access`). No new permission logic is needed.
- **Existing layering pattern to mirror** (from `subjects`/`measurements`
  verticals):
  `app/models` (ORM) → `app/repositories` (raw ORM queries) →
  `app/domain` (dataclasses with `from_db(obj)`, `*ListingParams`,
  `PaginatedResult[T]` from `app/domain/pagination.py`) →
  `app/services` (orchestration, converts ORM → domain) →
  `app/schemas` (Pydantic, `from_attributes=True`,
  `Model.model_validate(domain_obj)`) → `app/api/v1` (routes, builds
  `PaginatedResponse[T]`).
- **Reusable pieces already exist for both item shapes**:
  - Subject side: domain `SubjectBase` (`app/domain/subject.py:15-27` —
    `id, dni, sex, name, last_name`) / schema `SubjectSummaryResponse`
    (`app/schemas/subject_schema.py:65-73`) — exactly what
    `GET /subjects` returns per item today.
  - Measurement side: domain `MeasurementListItemDomain`
    (`app/domain/measurement.py:184-211`) / schema `MeasurementListItem`
    (`app/schemas/measurement_schema.py:100-111`) — full enriched item
    (subject ref, establishment ref, responsible ref, alerts), exactly
    what `GET /measurements` returns per item today.
  - Pagination: `PaginatedQueryParams` (`app/api/v1/params.py:13-18`),
    `PaginatedResult.build` (`app/domain/pagination.py`),
    `PaginatedResponse[T]` (`app/schemas/pagination.py`).
- **No migration needed** — no schema changes; only new read queries
  against `subjects`, `subject_events`, and `measurements`, all of which
  already exist.

### Key Discoveries / Gotchas

- **`actor.user_id` is a `str`, not a `UUID`.** `UserActor(user_id=payload["sub"], ...)`
  (`app/core/dependencies.py:95`) — `sub` is the JWT string claim, never
  coerced. A prior plan (`docs/plans/visualizacion_de_perfil_propio.md`)
  hit this exact issue with `Session.get()`. For this feature, coerce to
  `UUID(actor.user_id)` once in `ActivityService` before passing it to the
  repository, matching that precedent.
- **Merging two tables into one ordered, paginated feed requires a SQL
  `UNION ALL`, not an app-level merge.** Fetching top-N per type and
  merge-sorting in Python only works correctly for page 1; deeper pages
  can't be sliced correctly without over-fetching. The repository builds
  a `UNION ALL` of two minimal `(id, type, occurred_at)` selects, orders
  and paginates *that*, then runs a second hydration query per type for
  just the current page's ids.
- **Ties need a deterministic tiebreaker.** `ORDER BY occurred_at DESC`
  alone is not stable when two rows share a timestamp (SQL doesn't
  guarantee row order for ties) — add `id DESC` as a secondary sort key
  so pagination doesn't skip or repeat rows across pages.
- **`Measurement.alerts` is `lazy="selectin"`**
  (`app/models/measurement.py:45-50`), so it eager-loads automatically;
  `subject` and `establishment` and `responsible` still need explicit
  `selectinload` in the hydration query, same as
  `MeasurementRepository.get_measurement_listing`
  (`app/repositories/measurement_repository.py:92-101`).
- **Subject edits (`SUBJECT_UPDATED`) are intentionally excluded.** Only
  `SUBJECT_CREATED` events count as "publishing" a subject, keeping the
  two activity types symmetric (measurements have no update path either).

## Desired End State

`GET /api/v1/users/me/activity` with a valid bearer token returns `200`
and a paginated, date-descending feed of the caller's own subject
registrations and measurement uploads:

```jsonc
{
  "items": [
    {
      "type": "measurement",
      "occurred_at": "2026-06-30T14:00:00Z",
      "measurement": { "id": "…", "measured_at": "2026-06-30T14:00:00Z", "weight_kg": 12.4, "height_cm": 85.0, "bmi": 17.16, "subject": { "...": "..." }, "establishment": { "...": "..." }, "responsible": { "...": "..." }, "alerts": [] }
    },
    {
      "type": "subject",
      "occurred_at": "2026-06-29T09:12:00Z",
      "subject": { "id": "…", "dni": 12345678, "sex": "female", "name": "…", "last_name": "…" }
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

- `?type=subject` or `?type=measurement` restricts to one activity type;
  omitted returns both, merged.
- An admin/analyst calling this gets their own (typically empty)
  activity — no role restriction, since the query is inherently
  self-scoped.
- Ordering is by `occurred_at` descending: `subject_events.occurred_at`
  for subject items, `measurements.measured_at` for measurement items
  (not `measurements.created_at` — "published" tracks when the
  measurement was taken, matching the field worker's own sense of when
  they did the work, even if the upload synced later).

Verification: unit tests for `ActivityRepository`/`ActivityService`
covering merge ordering, pagination, and the type filter; integration
tests against a real Postgres container covering the full endpoint
(auth, pagination, filter, empty feed); manual `curl`/Swagger check.

## What We're NOT Doing

- Not touching `GET /measurements`'s admin/analyst restriction or adding
  a creator filter to `GET /subjects`.
- Not including `SUBJECT_UPDATED` events in the feed.
- Not adding a date-range filter or a configurable sort order (only
  newest-first) — no requirement calls for it.
- Not building any mobile/frontend UI — backend only.
- Not adding an Alembic migration — no schema changes.

## Implementation Approach

One vertical slice across all layers (domain → repository → service →
schema → route → wiring), since the feature is small, has no migration
gate, and there's nothing meaningful to verify mid-slice. Tests are a
separate phase so both unit and integration coverage can be written
against the finished interfaces.

## Phase 1: Vertical Slice (domain, repository, service, schema, route, wiring)

### Overview

Implement the full feature end-to-end: new domain types, the UNION-based
repository query, the service, the discriminated-union response schema,
the route, and registration in `UnitOfWork`/`dependencies.py`.

### Changes Required

#### 1. Domain

**File**: `app/domain/activity.py` (new)

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject import SubjectBase


class ActivityType(StrEnum):
    """Kinds of self-published activity surfaced in the recent-activity feed."""

    SUBJECT = "subject"
    MEASUREMENT = "measurement"


@dataclass
class ActivityListingParams:
    """Query parameters for the current user's activity feed."""

    activity_type: ActivityType | None = None


@dataclass
class ActivityItemDomain:
    """A single entry in a user's recent-activity feed.

    Exactly one of ``subject``/``measurement`` is set, matching ``type``.
    """

    type: ActivityType
    occurred_at: datetime
    subject: SubjectBase | None = None
    measurement: MeasurementListItemDomain | None = None
```

#### 2. Repository

**File**: `app/repositories/activity_repository.py` (new)

- `get_activity_feed(actor_id: UUID, limit: int, offset: int, activity_type: ActivityType | None) -> tuple[list[ActivityItemDomain], int]`
- Step 1 — build the id/type/timestamp `UNION ALL`:
  ```python
  subject_rows = (
      select(
          Subject.id.label("id"),
          literal(ActivityType.SUBJECT.value).label("type"),
          SubjectEvent.occurred_at.label("occurred_at"),
      )
      .select_from(SubjectEvent)
      .join(Subject, Subject.id == SubjectEvent.subject_id)
      .where(
          SubjectEvent.actor_id == actor_id,
          SubjectEvent.event_type == SubjectEventType.SUBJECT_CREATED,
      )
  )
  measurement_rows = select(
      Measurement.id.label("id"),
      literal(ActivityType.MEASUREMENT.value).label("type"),
      Measurement.measured_at.label("occurred_at"),
  ).where(Measurement.responsible_id == actor_id)
  ```
  Apply the `activity_type` filter (skip the irrelevant branch entirely,
  or `union_all` both and filter — skipping the branch is cheaper and
  simpler when `activity_type` is set) before unioning.
- Step 2 — count, then paginate the union subquery, ordered
  `occurred_at DESC, id DESC`:
  ```python
  feed = union_all(subject_rows, measurement_rows).subquery()
  total = await self.db.scalar(select(func.count()).select_from(feed))
  page_rows = (
      await self.db.execute(
          select(feed.c.id, feed.c.type)
          .order_by(feed.c.occurred_at.desc(), feed.c.id.desc())
          .limit(limit)
          .offset(offset)
      )
  ).all()
  ```
- Step 3 — split `page_rows` by type into id lists, run two hydration
  queries preserving full data needed for each schema:
  - Subjects: `select(Subject).where(Subject.id.in_(subject_ids))` (no
    joins needed — `SubjectBase` only reads scalar columns).
  - Measurements: same shape as
    `MeasurementRepository.get_measurement_listing`
    (`app/repositories/measurement_repository.py:92-101`) — join
    `Subject`/`Establishment`, `selectinload` `subject`, `establishment`,
    `responsible`, filtered by `Measurement.id.in_(measurement_ids)`.
- Step 4 — reassemble in the original `page_rows` order (a dict keyed by
  id per type, looked up in the union's order) into
  `list[ActivityItemDomain]`, using `SubjectBase.from_db` /
  `MeasurementListItemDomain.from_db`, and return `(items, total)`.

#### 3. Unit of Work wiring

**Files**: `app/core/interfaces/unit_of_work.py`, `app/db/unit_of_work.py`

- Add `activity_repo: ActivityRepository` to `IUnitOfWork`.
- Add `self.activity_repo = ActivityRepository(self.session)` in
  `UnitOfWork.__aenter__`, alongside the other repos.

#### 4. Service

**File**: `app/services/activity_service.py` (new)

```python
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.activity import ActivityItemDomain, ActivityListingParams
from app.domain.pagination import PaginatedResult
from app.domain.user import UserActor


class ActivityService:
    """Business logic for a user's own recent-activity feed."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_recent_activity(
        self,
        actor: UserActor,
        page: int,
        page_size: int,
        params: ActivityListingParams,
    ) -> PaginatedResult[ActivityItemDomain]:
        """Return the caller's own subjects-created and measurements-taken,
        merged into one date-descending feed."""
        page = max(1, page)
        offset = (page - 1) * page_size
        items, total = await self.uow.activity_repo.get_activity_feed(
            actor_id=UUID(actor.user_id),
            limit=page_size,
            offset=offset,
            activity_type=params.activity_type,
        )
        return PaginatedResult.build(
            items=items, total=total, page=page, page_size=page_size
        )
```

#### 5. Schemas

**File**: `app/schemas/activity_schema.py` (new)

```python
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.domain.activity import ActivityType
from app.schemas.measurement_schema import MeasurementListItem
from app.schemas.subject_schema import SubjectSummaryResponse


class SubjectActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal[ActivityType.SUBJECT]
    occurred_at: datetime
    subject: SubjectSummaryResponse


class MeasurementActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal[ActivityType.MEASUREMENT]
    occurred_at: datetime
    measurement: MeasurementListItem


ActivityItem = Annotated[
    Union[SubjectActivityItem, MeasurementActivityItem],
    Field(discriminator="type"),
]
```

Note: `SubjectActivityItem`/`MeasurementActivityItem` are built explicitly
in the route (not via a single `model_validate` on `ActivityItemDomain`,
since the domain dataclass carries both optional fields) — same pattern
already used for mapping lists in `list_subjects`/`list_measurements`.

#### 6. Route

**File**: `app/api/v1/users.py`

- Add `GET /users/me/activity`:
  ```python
  @router.get(
      "/me/activity",
      response_model=PaginatedResponse[ActivityItem],
      status_code=status.HTTP_200_OK,
      summary="Get the current user's recent activity",
      description=(
          "Returns a paginated, date-descending feed of the caller's own "
          "subject registrations and measurement uploads. Optionally filter "
          "to a single activity type. Accessible by all authenticated roles."
      ),
      responses={
          status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
      },
  )
  async def get_my_activity(
      paginated: PaginatedQueryParams = Depends(),
      type: ActivityType | None = Query(default=None),
      actor: UserActor = Depends(require_any),
      service: ActivityService = Depends(get_activity_service),
  ) -> PaginatedResponse[ActivityItem]:
      result = await service.get_recent_activity(
          actor,
          page=paginated.page,
          page_size=paginated.page_size,
          params=ActivityListingParams(activity_type=type),
      )
      items = [
          SubjectActivityItem(occurred_at=i.occurred_at, subject=SubjectSummaryResponse.model_validate(i.subject))
          if i.type == ActivityType.SUBJECT
          else MeasurementActivityItem(occurred_at=i.occurred_at, measurement=MeasurementListItem.model_validate(i.measurement))
          for i in result.items
      ]
      return PaginatedResponse[ActivityItem](
          items=items, total=result.total, page=result.page,
          page_size=result.page_size, total_pages=result.total_pages,
      )
  ```
  (`type=SubjectActivityItem.type: Literal[...]` needs the literal value
  set explicitly in the constructor call, e.g.
  `SubjectActivityItem(type=ActivityType.SUBJECT, ...)` — spelled out
  fully when writing the code, abbreviated here for readability.)

#### 7. Dependency wiring

**File**: `app/core/dependencies.py`

- Add:
  ```python
  async def get_activity_service() -> AsyncGenerator[ActivityService, None]:
      """Provide an ActivityService backed by a fresh UnitOfWork."""
      async with UnitOfWork() as uow:
          yield ActivityService(uow)
  ```

### Success Criteria

#### Automated Verification

- [x] Lint + format pass exactly as CI does: `poetry run pre-commit run --all-files`
- [x] No migration generated/needed: confirm `poetry run alembic upgrade head` is a no-op (no new revision file added)
- [x] App boots and route is registered: `poetry run uvicorn app.main:app --reload` starts without import errors, `GET /api/v1/users/me/activity` appears at `/docs`

#### Manual Verification

- [x] `GET /users/me/activity` via `/docs` or `curl` with a field-worker token returns their own subjects/measurements merged and ordered by date descending
- [x] `?type=subject` and `?type=measurement` each restrict to one type; omitted returns both
- [x] A user with zero activity gets `{"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0}`
- [x] An admin/analyst token gets their own (likely empty) feed, not `403`
- [x] Response shape matches the discriminated union (`type` field present and correct on every item) in Swagger's rendered schema

---

## Phase 2: Tests

### Overview

Cover the merge/pagination/filter logic at the unit level (mocked
session) and the full endpoint behavior at the integration level (real
Postgres via Testcontainers).

### Changes Required

#### 1. Unit tests

**File**: `tests/unit/test_activity_service.py` (new)

- `ActivityService.get_recent_activity` coerces `actor.user_id` (str) to
  `UUID` before calling the repo (mock `uow.activity_repo.get_activity_feed`
  and assert the `actor_id` kwarg is a `UUID` instance).
- Pagination math (`page`, `page_size`, `offset`) matches the pattern in
  `test_measurement_service.py`.
- `ActivityListingParams(activity_type=...)` is passed through unchanged.

**File**: `tests/unit/test_activity_repository.py` (new, or fold into an
integration test if a real DB is needed to exercise `UNION ALL`
correctly — SQLite-in-memory won't match Postgres UUID/enum handling, so
prefer covering the union/ordering/pagination logic in the integration
suite instead, per the codebase's existing split of repository-level DB
behavior into `tests/integration/`).

#### 2. Integration tests

**File**: `tests/integration/test_activity.py` (new)

Modeled after `tests/integration/test_measurement_listing.py` and
`tests/integration/test_subject.py`:

- Field worker creates 1 subject and 2 measurements (for possibly
  different subjects) → `GET /users/me/activity` returns 3 items, ordered
  by `occurred_at` descending, each with the correct `type` and nested
  payload.
- A second field worker's activity does not leak into the first's feed.
- `?type=subject` returns only the subject item; `?type=measurement`
  returns only the two measurement items.
- Pagination: create enough items to span 2 pages, verify `page=2`
  returns the next slice with no duplicates/gaps (exercises the
  `occurred_at, id` tiebreak).
- No token → `401`.
- Admin token with no activity of their own → `200` with an empty list.

### Success Criteria

#### Automated Verification

- [x] Lint + format pass exactly as CI does: `poetry run pre-commit run --all-files`
- [x] Unit tests pass: `poetry run pytest tests/unit/test_activity_service.py`
- [x] Full suite passes (requires Docker for Testcontainers): `poetry run pytest`
- [x] Coverage holds: `poetry run pytest --cov=app`

#### Manual Verification

- [x] Re-run the Phase 1 manual checks after tests are in place to confirm no regressions
- [x] Pagination edge case (exactly `page_size` items, requesting `page=2`) returns an empty-but-valid page, not an error

## Performance Considerations

- The `UNION ALL` + count query runs against `subject_events ⋈ subjects`
  (filtered on `actor_id`, indexed via the FK) and `measurements`
  (filtered on `responsible_id`, indexed via the FK) — both are narrow,
  per-user scans, not full-table scans. No new indexes required at
  current expected data volumes; revisit if a single field worker's
  activity grows into the tens of thousands of rows.
- The hydration step is two additional `IN (...)` queries bounded by
  `page_size` (max 100), not by the total feed size.

## Migration Notes

None — no schema changes. All new code reads from existing tables
(`subjects`, `subject_events`, `measurements`) via new queries only.

## References

- Grilling session (this conversation) — resolved: dedicated endpoint vs.
  reusing `/subjects` and `/measurements`; interleaved feed vs. separate
  arrays; `measured_at` vs `created_at` for sort; SQL `UNION ALL` vs.
  app-level merge; rich reused schemas vs. slim shape; `type` filter
  scope; `SUBJECT_CREATED`-only vs. including edits; new
  repo/service vs. bolting onto existing ones; discriminated union vs.
  flat-optional response; item id choice.
- Similar precedent: `docs/plans/visualizacion_de_perfil_propio.md` (own
  profile view — self-scoped read endpoint, `actor.user_id` str→UUID
  gotcha).
- Pattern to mirror: `app/services/measurement_service.py`,
  `app/repositories/measurement_repository.py`,
  `app/api/v1/measurements.py` (listing endpoint), `app/api/v1/subjects.py`.
- Conventions: `docs/conventions.md`, `docs/architecture.md`, `docs/auth.md`.
