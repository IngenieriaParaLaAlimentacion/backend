# Anthropometric Measurement Upload Implementation Plan

## Overview

Implement an idempotent `POST /api/v1/measurements` endpoint that registers a height/weight
measurement for a subject. The mobile app is offline-first: the client generates a UUID before
going offline and sends it as the `id` field in the request body on every sync attempt. That
client-supplied `id` becomes the measurement's primary key — no separate idempotency-key column
exists. If `id` is omitted, the server generates one. BMI is computed and stored server-side.
Clinical alerts are generated using WHO BMI-for-age z-scores for subjects under 19 years, and
WHO adult BMI thresholds for subjects 19 and older.

This mirrors the offline-first idempotent-create pattern already used for subjects
(see `app/services/subject_service.py`, `app/repositories/subject_repository.py`): the client
id is the primary key, a pre-check replay short-circuits repeat submissions, and a
SAVEPOINT-wrapped insert with `IntegrityError` → `UniqueConstraintError` translation handles
concurrent-insert races.

Covers acceptance criteria CA1–CA8 from `docs/upload-us.md`.

## Current State Analysis

**What already exists:**
- `app/models/measurement.py` — `Measurement` ORM model with `subject_id`, `responsible_id`,
  `establishment_id`, `weight_kg`, `height_cm`, `measured_at`, `synced_at`, `created_at`.
  Missing: `bmi`, `alerts` relationship.
- `alembic/versions/235b18ab1498_initial_schema.py` — `measurements` table created with the
  columns above. No `bmi`, no `measurement_alerts` table.
- `app/repositories/subject_repository.py` — `SubjectRepository` exists.
- `app/repositories/user_establishment_repository.py` — `UserEstablishmentRepository` exists
  but has no method to look up a single user↔establishment relation by both IDs.
- `app/core/interfaces/unit_of_work.py` — `IUnitOfWork` has no `measurement_repo` or
  `measurement_alert_repo`.
- `app/db/unit_of_work.py` — concrete `UnitOfWork` has no measurement repos.

**What does not exist yet:**
- `app/models/measurement_alert.py`
- `app/domain/measurement.py`
- `app/repositories/measurement_repository.py`
- `app/repositories/measurement_alert_repository.py`
- `app/services/measurement_service.py`
- `app/schemas/measurement_schema.py`
- `app/api/v1/measurements.py`
- `app/data/who_bmi_for_age.py`

**Flat file structure** — this codebase does not use per-module subdirectories inside
`repositories/` or `services/`. New files follow the existing flat pattern.

**Establishment middleware is not implemented** — `docs/auth.md` describes a centralized
middleware for per-establishment access checks, but it does not exist in the current codebase.
The service will perform this check directly against `user_establishments` as a temporary
measure. Add a `TODO` comment so it is removed when the middleware lands.

## Desired End State

A `POST /api/v1/measurements` endpoint that:
- Returns `201 Created` on the first upload for a given client-supplied `id` (or when `id` is
  omitted).
- Returns `200 OK` on a subsequent upload of the same `id` with the stored record unchanged.
- Validates subject and establishment exist, and that the requesting field worker has approved access.
- Validates anthropometric ranges (422 for impossible values).
- Computes and stores BMI.
- Generates clinical alerts using WHO standards.
- Returns the full measurement including any alerts in the response.

Verify with:
```bash
poetry run pre-commit run --all-files
poetry run alembic upgrade head
poetry run alembic downgrade -1 && poetry run alembic upgrade head
poetry run pytest
```

### Key Discoveries

- `Measurement` ORM is at `app/models/measurement.py:10`. Needs two new columns and a
  relationship to alerts.
- `IUnitOfWork` is at `app/core/interfaces/unit_of_work.py:15`. Must declare two new repo fields.
- `UnitOfWork.__aenter__` is at `app/db/unit_of_work.py:24`. Must instantiate the new repos.
- `UserEstablishmentRepository` at `app/repositories/user_establishment_repository.py` needs a
  new `get_approved_relation()` method (single user + establishment lookup).
- Router registration: add `measurements` router to `app/api/v1/router.py:6`.
- Exception handlers at `app/exceptions/domain_exceptions.py` are extended for measurements
  (no new base classes needed — reuse `NotFoundError` / `ForbiddenError`).

## What We Are NOT Doing

- Implementing the centralized establishment access middleware (deferred).
- Pediatric z-score calculation beyond the 0–228 month range covered by WHO tables.
- Updating or deleting measurements (upload only).
- Listing measurements (dashboard is a separate module).
- Any mobile offline storage or sync protocol — the backend only handles the HTTP upload.

## Implementation Approach

Layers are built bottom-up following the codebase convention:
model → migration → repository → service → schema → API route → tests.

The idempotency mechanism is the `Measurement.id` primary key itself (`UUID`, `default=uuid.uuid4`,
settable by the client) — there is no separate idempotency-key column. The service does a
pre-check `get_by_id()` before insert; if a concurrent request races the same id, the repository's
`create()` wraps the insert in a SAVEPOINT and translates the resulting `IntegrityError` into a
`UniqueConstraintError`, which the service catches and resolves by re-querying for the row that
won the race. Clinical alerts are only generated on first insert; replays return the existing
record and its stored alerts.

---

## Phase 1 — Schema: Migration + Models

### Overview

Add `bmi` to the `measurements` table; create the `measurement_alerts` table; update the
`Measurement` ORM model; add the new `MeasurementAlert` ORM model. The existing `id` column
(`UUID`, `default=uuid.uuid4`) doubles as the idempotency key — no new column needed for it.

### Changes Required

#### 1. Alembic migration

Generate with:
```bash
poetry run alembic revision --autogenerate -m "add bmi to measurements, add measurement_alerts"
```

Review the generated file and ensure it contains:

```python
def upgrade() -> None:
    op.add_column(
        "measurements",
        sa.Column("bmi", sa.Float(), nullable=False),
    )
    op.create_table(
        "measurement_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("measurement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "alert_type",
            sa.Enum(
                "severely_wasted",
                "wasted",
                "overweight",
                "obese",
                "severe_underweight",
                "underweight",
                name="alerttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("critical", "high", "medium", name="alertseverity"),
            nullable=False,
        ),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["measurement_id"], ["measurements.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_measurement_alerts_measurement_id",
        "measurement_alerts",
        ["measurement_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_measurement_alerts_measurement_id", table_name="measurement_alerts")
    op.drop_table("measurement_alerts")
    sa.Enum(name="alertseverity").drop(op.get_bind())
    sa.Enum(name="alerttype").drop(op.get_bind())
    op.drop_column("measurements", "bmi")
```

#### 2. Update `app/models/measurement.py`

Add the `bmi` column and the `alerts` relationship (the existing `id` column already serves
as the client-settable idempotency key):

```python
bmi = Column(Float, nullable=False)

alerts = relationship(
    "MeasurementAlert",
    back_populates="measurement",
    cascade="all, delete-orphan",
    lazy="selectin",
)
```

#### 3. New `app/models/measurement_alert.py`

```python
import uuid

from sqlalchemy import Column, DateTime, String, ForeignKey, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.measurement import AlertSeverity, AlertType
from .base import Base


class MeasurementAlert(Base):
    """Clinical alert generated when a measurement indicates nutritional risk."""

    __tablename__ = "measurement_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    measurement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("measurements.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type = Column(
        SAEnum(AlertType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    severity = Column(
        SAEnum(AlertSeverity, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    detail = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    measurement = relationship("Measurement", back_populates="alerts")
```

#### 4. Update `app/models/__init__.py`

Add `MeasurementAlert` to the imports and `__all__`.

### Success Criteria

#### Automated Verification

- [x] `poetry run pre-commit run --all-files`
- [ ] `poetry run alembic upgrade head` applies without error
- [ ] `poetry run alembic downgrade -1 && poetry run alembic upgrade head` round-trips cleanly
- [x] `poetry run pytest tests/unit/` (no new tests yet but existing suite must stay green)

#### Manual Verification

- [ ] `\d measurements` in psql shows `bmi` (float, not null)
- [ ] `\d measurement_alerts` shows the table with correct FK to `measurements`

---

## Phase 2 — Repository + Unit of Work ✓

### Overview

Add `MeasurementRepository`, `MeasurementAlertRepository`, a new method to
`UserEstablishmentRepository`, and wire everything into `IUnitOfWork` / `UnitOfWork`.

### Changes Required

#### 1. New `app/repositories/measurement_repository.py`

Mirrors `SubjectRepository`: `get_by_id()` is a direct PK lookup, and `create()` accepts an
optional client-supplied `id`, inserting inside a SAVEPOINT so a unique violation (id collision)
rolls back only the failed row and leaves the session usable for the caller to re-query.

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.measurement import Measurement


class MeasurementRepository:
    """Persistence operations for Measurement entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, measurement_id: UUID) -> Measurement | None:
        """Return a measurement by id, or None if it does not exist."""
        return await self.db.get(Measurement, measurement_id)

    async def create(
        self,
        *,
        id: UUID | None,
        subject_id: UUID,
        responsible_id: UUID,
        establishment_id: UUID,
        weight_kg: float,
        height_cm: float,
        bmi: float,
        measured_at: datetime,
    ) -> Measurement:
        """Persist a new measurement. ``id`` is optional; when None the server
        generates it.

        Raises:
            UniqueConstraintError: If the id is already in use. The caller is
                responsible for re-querying to decide the outcome.
        """
        fields = dict(
            subject_id=subject_id,
            responsible_id=responsible_id,
            establishment_id=establishment_id,
            weight_kg=weight_kg,
            height_cm=height_cm,
            bmi=bmi,
            measured_at=measured_at,
        )
        if id is not None:
            fields["id"] = id
        measurement = Measurement(**fields)
        try:
            async with self.db.begin_nested():
                self.db.add(measurement)
                await self.db.flush()
        except IntegrityError:
            raise UniqueConstraintError("id", id)
        await self.db.refresh(measurement)
        return measurement
```

#### 2. New `app/repositories/measurement_alert_repository.py`

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.measurement import AlertSeverity, AlertType
from app.models.measurement_alert import MeasurementAlert


class MeasurementAlertRepository:
    """Persistence operations for MeasurementAlert entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_bulk(
        self,
        measurement_id: UUID,
        alerts: list[tuple[AlertType, AlertSeverity, str]],
    ) -> list[MeasurementAlert]:
        """Persist a batch of alerts for a single measurement."""
        rows = [
            MeasurementAlert(
                measurement_id=measurement_id,
                alert_type=alert_type,
                severity=severity,
                detail=detail,
            )
            for alert_type, severity, detail in alerts
        ]
        self.db.add_all(rows)
        await self.db.flush()
        return rows

    async def get_by_measurement_id(
        self, measurement_id: UUID
    ) -> list[MeasurementAlert]:
        """Return all alerts for the given measurement."""
        result = await self.db.execute(
            select(MeasurementAlert).where(
                MeasurementAlert.measurement_id == measurement_id
            )
        )
        return list(result.scalars().all())
```

#### 3. Add `get_relation()` to `app/repositories/user_establishment_repository.py`

```python
async def get_relation(
    self, user_id: UUID, establishment_id: UUID
) -> UserEstablishment | None:
    """Return the user-establishment relation regardless of status, or None."""
    result = await self.db.execute(
        select(UserEstablishment).where(
            UserEstablishment.user_id == user_id,
            UserEstablishment.establishment_id == establishment_id,
        )
    )
    return result.scalar_one_or_none()
```

The status check (`APPROVED`) belongs in the service layer, not here.

#### 4. Update `app/core/interfaces/unit_of_work.py`

Add the two new repo fields:

```python
from app.repositories.measurement_repository import MeasurementRepository
from app.repositories.measurement_alert_repository import MeasurementAlertRepository

class IUnitOfWork(ABC):
    ...
    measurement_repo: MeasurementRepository
    measurement_alert_repo: MeasurementAlertRepository
```

#### 5. Update `app/db/unit_of_work.py`

Instantiate both repos in `__aenter__`:

```python
from app.repositories.measurement_repository import MeasurementRepository
from app.repositories.measurement_alert_repository import MeasurementAlertRepository

self.measurement_repo = MeasurementRepository(self.session)
self.measurement_alert_repo = MeasurementAlertRepository(self.session)
```

### Success Criteria

#### Automated Verification

- [x] `poetry run pre-commit run --all-files`
- [x] `poetry run pytest tests/unit/`

---

## Phase 3 — Clinical Logic + Service ✓

### Overview

Embed WHO BMI-for-age LMS reference tables; implement z-score calculation; implement domain
enums; implement `MeasurementService` with idempotent registration and alert generation.

### Changes Required

#### 1. New `app/data/who_bmi_for_age.py`

This module holds the WHO LMS parameters as a static dictionary keyed by
`(sex_value: str, age_months: int) → (L: float, M: float, S: float)`.

Sources:
- 0–60 months (boys + girls): WHO Child Growth Standards
  `https://www.who.int/tools/child-growth-standards/standards/body-mass-index-for-age`
- 61–228 months (boys + girls): WHO Reference 2007
  `https://www.who.int/tools/growth-reference-data-for-5to19-years/indicators/bmi-for-age`

Structure:
```python
# Keys: ("male" | "female", age_in_months)  Values: (L, M, S)
WHO_BMI_LMS: dict[tuple[str, int], tuple[float, float, float]] = {
    ("male", 0): (L, M, S),
    ("male", 1): (L, M, S),
    # ... all monthly entries 0–228 for male
    ("female", 0): (L, M, S),
    # ... all monthly entries 0–228 for female
}
```

Fill the actual L, M, S values by copying from the WHO Excel/CSV files linked above
(columns `L`, `M`, `S` in each table). Round to 6 decimal places.

#### 2. New `app/domain/measurement.py`

> **Note:** in the final implementation the clinical-logic functions below
> (`age_in_months`, `compute_bmi_z_score`, `evaluate_alerts`) live in
> `app/utils/anthropometry.py`, not `app/domain/measurement.py`. `app/domain/measurement.py`
> holds only the enums and the `AlertDomain` / `MeasurementDomain` dataclasses shown here.

```python
import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from app.data.who_bmi_for_age import WHO_BMI_LMS
from app.domain.subject import Sex


class AlertType(str, Enum):
    SEVERELY_WASTED = "severely_wasted"   # z < -3  (children)
    WASTED = "wasted"                     # -3 ≤ z < -2  (children)
    OVERWEIGHT = "overweight"             # z > 2 (children) | BMI ≥ 25 (adult)
    OBESE = "obese"                       # z > 3 (children) | BMI ≥ 30 (adult)
    SEVERE_UNDERWEIGHT = "severe_underweight"  # BMI < 16  (adult only)
    UNDERWEIGHT = "underweight"           # 16 ≤ BMI < 18.5  (adult only)


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


@dataclass
class AlertDomain:
    id: UUID
    measurement_id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    detail: str
    created_at: datetime

    @classmethod
    def from_db(cls, obj) -> "AlertDomain":
        return cls(
            id=obj.id,
            measurement_id=obj.measurement_id,
            alert_type=obj.alert_type,
            severity=obj.severity,
            detail=obj.detail,
            created_at=obj.created_at,
        )


@dataclass
class MeasurementDomain:
    id: UUID
    subject_id: UUID
    responsible_id: UUID
    establishment_id: UUID
    weight_kg: float
    height_cm: float
    bmi: float
    measured_at: datetime
    created_at: datetime
    alerts: list[AlertDomain]

    @classmethod
    def from_db(cls, obj) -> "MeasurementDomain":
        return cls(
            id=obj.id,
            subject_id=obj.subject_id,
            responsible_id=obj.responsible_id,
            establishment_id=obj.establishment_id,
            weight_kg=obj.weight_kg,
            height_cm=obj.height_cm,
            bmi=obj.bmi,
            measured_at=obj.measured_at,
            created_at=obj.created_at,
            alerts=[AlertDomain.from_db(a) for a in obj.alerts],
        )


def age_in_months(birth_date: date, measured_at: datetime) -> int:
    """Return completed months between birth_date and the measurement date."""
    ref = measured_at.date()
    months = (ref.year - birth_date.year) * 12 + (ref.month - birth_date.month)
    if ref.day < birth_date.day:
        months -= 1
    return max(0, months)


def compute_bmi_z_score(bmi: float, sex: Sex, months: int) -> float | None:
    """Return BMI-for-age z-score using the WHO LMS method, or None if out of range."""
    lms = WHO_BMI_LMS.get((sex.value, months))
    if lms is None:
        return None
    l, m, s = lms
    if abs(l) < 1e-10:
        return math.log(bmi / m) / s
    return ((bmi / m) ** l - 1) / (l * s)


def evaluate_alerts(
    bmi: float, sex: Sex, birth_date: date, measured_at: datetime
) -> list[tuple[AlertType, AlertSeverity, str]]:
    """Return (alert_type, severity, detail) tuples for the given measurement."""
    months = age_in_months(birth_date, measured_at)

    if months < 228:  # under 19 years — use WHO z-scores
        z = compute_bmi_z_score(bmi, sex, months)
        if z is None:
            return []
        if z < -3:
            return [(AlertType.SEVERELY_WASTED, AlertSeverity.CRITICAL,
                     f"BMI-for-age z-score {z:.2f} < -3 SD: severe acute malnutrition.")]
        if z < -2:
            return [(AlertType.WASTED, AlertSeverity.HIGH,
                     f"BMI-for-age z-score {z:.2f} < -2 SD: moderate acute malnutrition.")]
        if z > 3:
            return [(AlertType.OBESE, AlertSeverity.HIGH,
                     f"BMI-for-age z-score {z:.2f} > +3 SD: obese.")]
        if z > 2:
            return [(AlertType.OVERWEIGHT, AlertSeverity.MEDIUM,
                     f"BMI-for-age z-score {z:.2f} > +2 SD: overweight.")]
        return []

    # Adult (≥ 19 years) — use WHO adult BMI thresholds
    if bmi < 16:
        return [(AlertType.SEVERE_UNDERWEIGHT, AlertSeverity.CRITICAL,
                 f"BMI {bmi:.1f} < 16: severe underweight.")]
    if bmi < 18.5:
        return [(AlertType.UNDERWEIGHT, AlertSeverity.HIGH,
                 f"BMI {bmi:.1f} < 18.5: underweight.")]
    if bmi >= 30:
        return [(AlertType.OBESE, AlertSeverity.HIGH,
                 f"BMI {bmi:.1f} ≥ 30: obese.")]
    if bmi >= 25:
        return [(AlertType.OVERWEIGHT, AlertSeverity.MEDIUM,
                 f"BMI {bmi:.1f} ≥ 25: overweight.")]
    return []
```

#### 3. New `app/services/measurement_service.py`

Mirrors `SubjectService.create_subject()`: pre-check by id for a replay, otherwise validate and
insert, with a `UniqueConstraintError` recovery path for concurrent-insert races.

```python
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import UserEstablishmentStatus
from app.domain.measurement import MeasurementDomain
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.models.subject import Subject
from app.schemas.measurement_schema import MeasurementRequest
from app.utils.anthropometry import evaluate_alerts


class MeasurementService:
    """Business logic for anthropometric measurement registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _get_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

    async def _get_establishment_or_raise(self, establishment_id: UUID) -> None:
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))

    # TODO: remove this check once the centralized establishment middleware is in place.
    async def _check_establishment_access(
            self, actor: UserActor, establishment_id: UUID
    ) -> None:
        if actor.role != UserRole.FIELD_WORKER:
            return
        relation = await self.uow.user_establishment_repo.get_relation(
            actor.user_id, establishment_id
        )
        if relation is None or relation.status != UserEstablishmentStatus.APPROVED:
            raise ForbiddenError()

    async def register(
            self,
            data: MeasurementRequest,
            actor: UserActor,
    ) -> tuple[MeasurementDomain, bool]:
        """Idempotently register a measurement.

        Returns a ``(measurement, created)`` tuple: ``created`` is True for a brand-new
        measurement (201) and False for an idempotent replay of an existing id (200).

        Raises:
            SubjectNotFoundError: subject_id does not exist.
            EstablishmentNotFoundError: establishment_id does not exist.
            ForbiddenError: field worker lacks approved access to the establishment.
        """
        # Idempotent replay: same client id already stored.
        if data.id is not None:
            existing = await self.uow.measurement_repo.get_by_id(data.id)
            if existing is not None:
                return MeasurementDomain.from_db(existing), False

        subject = await self._get_subject_or_raise(data.subject_id)
        await self._get_establishment_or_raise(data.establishment_id)
        await self._check_establishment_access(actor, data.establishment_id)

        bmi = data.weight_kg / (data.height_cm / 100) ** 2

        try:
            measurement = await self.uow.measurement_repo.create(
                id=data.id,
                subject_id=data.subject_id,
                responsible_id=actor.user_id,
                establishment_id=data.establishment_id,
                weight_kg=data.weight_kg,
                height_cm=data.height_cm,
                bmi=bmi,
                measured_at=data.measured_at,
            )
        except UniqueConstraintError:
            # Concurrent insert of the same id (race) -> treat as replay.
            if data.id is not None:
                raced = await self.uow.measurement_repo.get_by_id(data.id)
                if raced is not None:
                    return MeasurementDomain.from_db(raced), False
            raise

        raw_alerts = evaluate_alerts(
            bmi=bmi,
            sex=subject.sex,
            birth_date=subject.birth_date,
            measured_at=data.measured_at,
        )
        if raw_alerts:
            # Assign directly rather than re-querying: `measurement.alerts` was already
            # lazy-loaded as empty by `db.refresh()` in `create()`, before these rows
            # existed, so accessing it again would return that stale cached collection.
            measurement.alerts = await self.uow.measurement_alert_repo.create_bulk(
                measurement.id, raw_alerts
            )

        await self.uow.commit()
        return MeasurementDomain.from_db(measurement), True
```

#### 4. Add `get_measurement_service()` to `app/core/dependencies.py`

```python
from app.services.measurement_service import MeasurementService

async def get_measurement_service() -> AsyncGenerator[MeasurementService, None]:
    """Provide a MeasurementService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield MeasurementService(uow)
```

### Success Criteria

#### Automated Verification

- [ ] `poetry run pre-commit run --all-files`
- [ ] `poetry run pytest tests/unit/` (new unit tests below must pass)

#### Manual Verification

- [ ] `evaluate_alerts()` with a 3-year-old male, z < -3 → returns `SEVERELY_WASTED / CRITICAL`
- [ ] `evaluate_alerts()` with a 25-year-old, BMI 27 → returns `OVERWEIGHT / MEDIUM`
- [ ] `evaluate_alerts()` with a healthy child → returns empty list

---

## Phase 4 — Schema + API Route

### Overview

Define Pydantic request/response schemas and expose the endpoint.

### Changes Required

#### 1. New `app/schemas/measurement_schema.py`

```python
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.measurement import AlertSeverity, AlertType


class MeasurementRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID for offline-first idempotency. When provided it "
            "becomes the measurement's primary key and repeated submissions with "
            "the same id are idempotent. When omitted, the server generates one."
        ),
    )
    subject_id: UUID
    establishment_id: UUID
    weight_kg: float = Field(gt=0.5, le=300, description="Weight in kilograms.")
    height_cm: float = Field(gt=20.0, le=250.0, description="Height in centimetres.")
    measured_at: datetime

    @field_validator("measured_at")
    @classmethod
    def measured_at_not_future(cls, v: datetime) -> datetime:
        if v > datetime.now(timezone.utc):
            raise ValueError("measured_at cannot be in the future")
        return v


class AlertResponse(BaseModel):
    alert_type: AlertType
    severity: AlertSeverity
    detail: str

    model_config = {"from_attributes": True}


class MeasurementResponse(BaseModel):
    id: UUID
    subject_id: UUID
    responsible_id: UUID
    establishment_id: UUID
    weight_kg: float
    height_cm: float
    bmi: float
    measured_at: datetime
    created_at: datetime
    alerts: list[AlertResponse]

    model_config = {"from_attributes": True}
```

#### 2. New `app/api/v1/measurements.py`

The `id` travels in the request body rather than the URL, since this is a `POST` (not a `PUT`
keyed by URL segment). The route declares `201` as its default status and downgrades to `200`
via an injected `Response` when the service reports a replay.

```python
from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import get_measurement_service, require_any
from app.domain import UserActor
from app.schemas.measurement_schema import MeasurementRequest, MeasurementResponse
from app.services.measurement_service import MeasurementService

router = APIRouter(prefix="/measurements")


@router.post(
    "",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an anthropometric measurement",
    description=(
        "Idempotent upload of a height/weight measurement for a subject. "
        "Replaying the same id returns the stored record unchanged. "
        "Clinical alerts are generated on first write using WHO standards."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Measurement already existed; idempotent replay of the "
            "same id."
        },
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {
            "description": "Subject or establishment not found"
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Weight, height, or date out of valid range"
        },
    },
)
async def upload_measurement(
    data: MeasurementRequest,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: MeasurementService = Depends(get_measurement_service),
) -> MeasurementResponse:
    measurement, created = await service.register(data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return MeasurementResponse.model_validate(measurement)
```

#### 3. Register the router in `app/api/v1/router.py`

```python
from app.api.v1 import admin, auth, establishments, measurements, subjects, users

v1_router.include_router(measurements.router, tags=["Measurements V1"])
```

### Success Criteria

#### Automated Verification

- [ ] `poetry run pre-commit run --all-files`
- [ ] `poetry run pytest`

#### Manual Verification

- [ ] `POST /api/v1/measurements` with valid payload → `201`, body contains `bmi` and `alerts`
- [ ] Same request repeated with the same body `id` → `200`, same body returned (idempotent)
- [ ] `weight_kg: 0` → `422`
- [ ] `measured_at` in the future → `422`
- [ ] Unknown `subject_id` → `404`
- [ ] Field worker calling with an establishment they don't have approved access to → `403`
- [ ] Admin calling → succeeds regardless of establishment relation

---

## Phase 5 — Tests

### Overview

Unit tests for clinical logic and service behavior; integration tests for the endpoint.

### Changes Required

#### 1. `tests/unit/test_measurement_domain.py`

- `evaluate_alerts()` for a 6-month-old male with z < -3 → `SEVERELY_WASTED / CRITICAL`
- `evaluate_alerts()` for a 10-year-old female with normal z → empty list
- `evaluate_alerts()` for a 25-year-old with BMI 17 → `UNDERWEIGHT / HIGH`
- `evaluate_alerts()` for a 25-year-old with BMI 32 → `OBESE / HIGH`
- `age_in_months()` edge cases: same day, day before birthday, leap year birth date
- `compute_bmi_z_score()` returns `None` for age outside 0–228 months

#### 2. `tests/unit/test_measurement_service.py`

Mock `IUnitOfWork` (following the pattern in `tests/unit/test_subject_service.py`):

- First call with a new (or omitted) `id` → inserts measurement, generates alerts, commits,
  returns `created=True`
- Replay with an `id` that already exists → returns existing, skips insert and alert
  generation, no commit, `created=False`
- Concurrent insert race (pre-check misses, `create()` raises `UniqueConstraintError`) →
  re-queries by id and returns the winning row as a replay
- Unknown `subject_id` → raises `SubjectNotFoundError`
- Unknown `establishment_id` → raises `EstablishmentNotFoundError`
- Field worker with no approved relation → raises `ForbiddenError`
- Admin with no establishment relation → succeeds (bypasses establishment check)

#### 3. `tests/integration/test_measurements.py`

Using Testcontainers (Docker required), following the pattern in
`tests/integration/test_subject.py`:

- `POST /api/v1/measurements` → `201`, correct payload shape
- A client-supplied `id` is used as the measurement's primary key
- Same `id` replayed → `200`, identical body, no duplicate row in DB
- Omitting `id` still creates a new measurement with a server-generated id
- Bad `weight_kg` (0.1) → `422`
- `measured_at` in the future → `422`
- Nonexistent `subject_id` → `404`
- Field worker without establishment access → `403`
- Measurement with severely low/high BMI → response includes the matching alert
- Replaying an `id` that triggered alerts does not duplicate the alert rows

### Success Criteria

#### Automated Verification

- [ ] `poetry run pytest tests/unit/`
- [ ] `poetry run pytest` (full suite including integration, requires Docker)
- [ ] `poetry run pytest --cov=app` — coverage does not regress

---

## Testing Strategy

### Unit Tests

Cover `tests/unit/` with mocked `IUnitOfWork`:
- All clinical alert paths (children z-scores, adult BMI, normal range = no alert)
- Idempotency logic (replay by id, first insert, concurrent-insert race recovery)
- Establishment access check for field worker vs admin roles
- BMI formula: `weight / (height/100)^2`

### Integration Tests

Cover `tests/integration/` via Testcontainers (real PostgreSQL):
- Full happy path end-to-end
- Idempotency: replaying the same `id` returns the same DB row, no duplicate
- Establishment permission enforcement
- All 422 validation paths

### Manual Testing Steps

1. Start the server: `poetry run uvicorn app.main:app --reload`
2. Open `/docs`, find `POST /api/v1/measurements`
3. Authenticate as a field worker with an approved establishment
4. Submit a measurement for a registered subject (with or without a client-supplied `id`)
5. Submit the same request again with the same `id` — confirm identical response (now `200`),
   no duplicate in DB
6. Submit with `weight_kg: 1000` — confirm `422`
7. Submit as a field worker for an establishment they don't belong to — confirm `403`
8. Submit as admin for any establishment — confirm `201`

---

## Performance Considerations

- `Measurement.id` is the primary key — lookup by id in `get_by_id()` is O(log n), no extra
  index needed.
- `ix_measurement_alerts_measurement_id` covers alert lookups by measurement.
- `Measurement.alerts` uses `lazy="selectin"` to avoid N+1 when loading a measurement. Because
  of this, freshly-inserted alert rows must be assigned directly onto `measurement.alerts`
  (see `register()` in Phase 3) rather than read back through the relationship, which would
  return the stale collection cached at the earlier `db.refresh()`.
- No pagination needed for alerts (a single measurement produces at most one alert).

## Migration Notes

- The `measurements` table has no production data at time of writing. `bmi NOT NULL` can be
  added directly without a backfill step.
- Rollback: `poetry run alembic downgrade -1` drops the `measurement_alerts` table and the
  `bmi` column. The `alerttype` and `alertseverity` Postgres enums are dropped in `downgrade()`.
- An earlier version of this migration also added a separate `idempotency_key UUID UNIQUE
  NOT NULL` column. That was removed before merge in favor of using `Measurement.id` itself
  as the client-settable identifier (mirroring `Subject.id`), so the migration file was edited
  in place rather than stacking a follow-up migration to drop the column — safe only because
  it had not yet been merged or applied to any shared database.

## References

- User story: `docs/upload-us.md`
- WHO Child Growth Standards (0–5 years): `https://www.who.int/tools/child-growth-standards/standards/body-mass-index-for-age`
- WHO Growth Reference 2007 (5–19 years): `https://www.who.int/tools/growth-reference-data-for-5to19-years/indicators/bmi-for-age`
- Existing pattern to model: `app/services/subject_service.py`, `app/repositories/subject_repository.py`
- Convention reference: `docs/conventions.md`, `docs/architecture.md`, `docs/auth.md`
