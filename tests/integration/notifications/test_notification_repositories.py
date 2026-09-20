import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.domain.establishment import UserEstablishmentStatus
from app.domain.food_outflow import FoodOutflowSource
from app.domain.notifications import PushPlatform
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_establishment import UserEstablishment
from app.models.establishments.establishment import Establishment
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.notifications.push_delivery_job import PushDeliveryJob
from app.models.notifications.stale_establishment_cycle import (
    StaleEstablishmentCycle,
)
from app.models.notifications.user_push_device import UserPushDevice
from app.repositories.notifications import (
    PushDeliveryJobRepository,
    StaleEstablishmentCycleRepository,
    UserPushDeviceRepository,
)

pytestmark = pytest.mark.asyncio

UTC = timezone.utc
ACTIVATED_AT = datetime(2026, 9, 19, 12, tzinfo=UTC)


def _establishment(name: str) -> Establishment:
    return Establishment(
        name=name,
        formatted_address=f"{name} address",
        latitude=-34.6,
        longitude=-58.4,
        place_id=f"place-{uuid.uuid4()}",
        city="Buenos Aires",
        province="Buenos Aires",
    )


def _user(
    label: str,
    *,
    role: UserRole = UserRole.FIELD_WORKER,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    return User(
        name=label,
        last_name="Notifications",
        email=f"{label}-{uuid.uuid4()}@test.com",
        role=role,
        status=status,
    )


def _outflow(
    establishment_id: uuid.UUID,
    responsible_id: uuid.UUID,
    occurred_at: datetime,
) -> FoodOutflow:
    return FoodOutflow(
        establishment_id=establishment_id,
        responsible_id=responsible_id,
        occurred_at=occurred_at,
        source=FoodOutflowSource.MANUAL,
    )


async def _create_cycle(
    session,
    establishment_id: uuid.UUID,
    *,
    started_at: datetime = ACTIVATED_AT,
    threshold: int = 168,
) -> StaleEstablishmentCycle:
    cycle = StaleEstablishmentCycle(
        establishment_id=establishment_id,
        last_outflow_at=started_at,
        started_at=started_at,
        next_threshold_hours=threshold,
        next_due_at=started_at + timedelta(hours=threshold),
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def _create_device(
    session,
    user_id: uuid.UUID,
    label: str,
) -> UserPushDevice:
    device = UserPushDevice(
        user_id=user_id,
        installation_id=f"installation-{label}",
        fcm_token=f"token-{label}",
        platform=PushPlatform.ANDROID,
        device_name=label,
    )
    session.add(device)
    await session.flush()
    return device


async def test_activity_advances_use_strict_event_time_and_skip_never_outflow(app):
    from app.db.database import AsyncSessionLocal

    older = ACTIVATED_AT - timedelta(days=30)
    newer = ACTIVATED_AT + timedelta(hours=2)
    async with AsyncSessionLocal() as session:
        with_outflow = _establishment("With outflow")
        without_outflow = _establishment("Without outflow")
        worker = _user("activity")
        session.add_all([with_outflow, without_outflow, worker])
        await session.flush()
        session.add(_outflow(with_outflow.id, worker.id, older))
        await session.commit()

        repository = StaleEstablishmentCycleRepository(session)
        advances = await repository.list_activity_advances()
        assert [(item.establishment_id, item.last_outflow_at) for item in advances] == [
            (with_outflow.id, older)
        ]

        started_at = max(older, ACTIVATED_AT)
        created = await repository.create_if_absent(
            establishment_id=with_outflow.id,
            last_outflow_at=older,
            started_at=started_at,
            next_threshold_hours=168,
            next_due_at=started_at + timedelta(hours=168),
        )
        assert created is not None
        assert created.next_due_at == ACTIVATED_AT + timedelta(hours=168)
        await session.commit()

        session.add_all(
            [
                _outflow(with_outflow.id, worker.id, older - timedelta(days=1)),
                _outflow(with_outflow.id, worker.id, older),
            ]
        )
        await session.commit()
        assert await repository.list_activity_advances() == []

        session.add(_outflow(with_outflow.id, worker.id, newer))
        await session.commit()
        advances = await repository.list_activity_advances()
        assert len(advances) == 1
        assert advances[0].last_outflow_at == newer
        assert max(newer, ACTIVATED_AT) + timedelta(hours=168) == newer + timedelta(
            hours=168
        )


async def test_registration_reassignment_uniqueness_and_owner_scoped_delete(app):
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        first = _user("first")
        second = _user("second")
        session.add_all([first, second])
        await session.flush()
        repository = UserPushDeviceRepository(session)

        device = await repository.upsert_installation(
            user_id=first.id,
            installation_id="shared-installation",
            fcm_token="token-a",
            platform=PushPlatform.ANDROID,
            device_name="First phone",
        )
        await session.commit()

        moved = await repository.upsert_installation(
            user_id=second.id,
            installation_id="shared-installation",
            fcm_token="token-b",
            platform=PushPlatform.IOS,
            device_name="Second phone",
        )
        await session.commit()
        assert moved.id == device.id
        assert moved.user_id == second.id
        assert moved.fcm_token == "token-b"

        other = await repository.upsert_installation(
            user_id=first.id,
            installation_id="other-installation",
            fcm_token="token-a",
            platform=PushPlatform.ANDROID,
            device_name=None,
        )
        await repository.delete_conflicting_token("token-b", other.installation_id)
        other = await repository.upsert_installation(
            user_id=first.id,
            installation_id=other.installation_id,
            fcm_token="token-b",
            platform=PushPlatform.ANDROID,
            device_name=None,
        )
        await session.commit()
        assert other.fcm_token == "token-b"
        assert (
            await session.scalar(select(func.count()).select_from(UserPushDevice)) == 1
        )

        assert (
            await repository.delete_for_user_installation(
                second.id, other.installation_id
            )
            == 0
        )
        assert (
            await repository.delete_for_user_installation(
                first.id, other.installation_id
            )
            == 1
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        owner = _user("constraints")
        session.add(owner)
        await session.flush()
        session.add_all(
            [
                UserPushDevice(
                    user_id=owner.id,
                    installation_id="duplicate",
                    fcm_token="unique-a",
                    platform=PushPlatform.ANDROID,
                ),
                UserPushDevice(
                    user_id=owner.id,
                    installation_id="duplicate",
                    fcm_token="unique-b",
                    platform=PushPlatform.ANDROID,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    async with AsyncSessionLocal() as session:
        owner = _user("token-constraints")
        session.add(owner)
        await session.flush()
        session.add_all(
            [
                UserPushDevice(
                    user_id=owner.id,
                    installation_id="unique-a",
                    fcm_token="duplicate-token",
                    platform=PushPlatform.ANDROID,
                ),
                UserPushDevice(
                    user_id=owner.id,
                    installation_id="unique-b",
                    fcm_token="duplicate-token",
                    platform=PushPlatform.ANDROID,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_recipient_listing_applies_every_current_eligibility_predicate(app):
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        target = _establishment("Target")
        other = _establishment("Other")
        included = _user("included")
        inactive = _user("inactive", status=UserStatus.INACTIVE)
        analyst = _user("analyst", role=UserRole.ANALYST)
        pending = _user("pending")
        revoked = _user("revoked")
        other_only = _user("other-only")
        session.add_all(
            [
                target,
                other,
                included,
                inactive,
                analyst,
                pending,
                revoked,
                other_only,
            ]
        )
        await session.flush()
        session.add_all(
            [
                UserEstablishment(
                    user_id=included.id,
                    establishment_id=target.id,
                    status=UserEstablishmentStatus.APPROVED,
                ),
                UserEstablishment(
                    user_id=inactive.id,
                    establishment_id=target.id,
                    status=UserEstablishmentStatus.APPROVED,
                ),
                UserEstablishment(
                    user_id=analyst.id,
                    establishment_id=target.id,
                    status=UserEstablishmentStatus.APPROVED,
                ),
                UserEstablishment(
                    user_id=pending.id,
                    establishment_id=target.id,
                    status=UserEstablishmentStatus.PENDING,
                ),
                UserEstablishment(
                    user_id=revoked.id,
                    establishment_id=target.id,
                    status=UserEstablishmentStatus.REVOKED,
                ),
                UserEstablishment(
                    user_id=other_only.id,
                    establishment_id=other.id,
                    status=UserEstablishmentStatus.APPROVED,
                ),
            ]
        )
        await session.flush()
        included_devices = [
            await _create_device(session, included.id, "included-1"),
            await _create_device(session, included.id, "included-2"),
        ]
        for user, label in [
            (inactive, "inactive"),
            (analyst, "analyst"),
            (pending, "pending"),
            (revoked, "revoked"),
            (other_only, "other"),
        ]:
            await _create_device(session, user.id, label)
        await session.commit()

        devices = await UserPushDeviceRepository(
            session
        ).list_eligible_for_establishment(target.id)
        assert {device.id for device in devices} == {
            device.id for device in included_devices
        }


async def test_due_cycle_locks_skip_concurrent_runner_and_rollback_is_atomic(app):
    from app.db.database import AsyncSessionLocal

    now = ACTIVATED_AT + timedelta(days=8)
    async with AsyncSessionLocal() as seed:
        establishment = _establishment("Locking")
        user = _user("locking")
        seed.add_all([establishment, user])
        await seed.flush()
        device = await _create_device(seed, user.id, "locking")
        cycle = await _create_cycle(seed, establishment.id)
        await seed.commit()
        cycle_id = cycle.id
        device_id = device.id
        establishment_id = establishment.id
        assert (
            await seed.scalar(select(func.count()).select_from(StaleEstablishmentCycle))
            == 1
        )

    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        first_rows = await StaleEstablishmentCycleRepository(first).list_due_for_update(
            now=now, limit=10
        )
        second_rows = await StaleEstablishmentCycleRepository(
            second
        ).list_due_for_update(now=now, limit=10)
        assert [row.id for row in first_rows] == [cycle_id]
        assert second_rows == []
        await first.rollback()
        await second.rollback()

    async with AsyncSessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(StaleEstablishmentCycle)
            )
            == 1
        )
        cycle = await StaleEstablishmentCycleRepository(session).get_for_update(
            establishment_id
        )
        assert cycle is not None
        await PushDeliveryJobRepository(session).create_for_devices(
            stale_cycle_id=cycle.id,
            threshold_hours=168,
            device_ids=[device_id],
            available_at=now,
        )
        cycle.next_threshold_hours = 336
        cycle.next_due_at = cycle.started_at + timedelta(hours=336)
        await session.rollback()

    async with AsyncSessionLocal() as session:
        cycle = await session.get(StaleEstablishmentCycle, cycle_id)
        assert cycle.next_threshold_hours == 168
        assert cycle.next_due_at == ACTIVATED_AT + timedelta(hours=168)
        assert (
            await session.scalar(select(func.count()).select_from(PushDeliveryJob)) == 0
        )


async def test_job_creation_context_leasing_retry_and_cycle_cancellation(app):
    from app.db.database import AsyncSessionLocal

    now = ACTIVATED_AT + timedelta(days=8)
    async with AsyncSessionLocal() as session:
        establishment = _establishment("Jobs")
        user = _user("jobs")
        session.add_all([establishment, user])
        await session.flush()
        first_device = await _create_device(session, user.id, "jobs-1")
        second_device = await _create_device(session, user.id, "jobs-2")
        cycle = await _create_cycle(session, establishment.id)
        repository = PushDeliveryJobRepository(session)
        jobs = await repository.create_for_devices(
            stale_cycle_id=cycle.id,
            threshold_hours=168,
            device_ids=[first_device.id, second_device.id],
            available_at=now,
        )
        cycle.next_threshold_hours = 336
        cycle.next_due_at = cycle.started_at + timedelta(hours=336)
        await session.commit()

        claimed = await repository.claim_due(
            now=now,
            claimed_until=now + timedelta(minutes=2),
            limit=10,
        )
        assert set(claimed) == {job.id for job in jobs}
        await session.commit()
        assert (
            await repository.claim_due(
                now=now + timedelta(minutes=1),
                claimed_until=now + timedelta(minutes=3),
                limit=10,
            )
            == []
        )

        reclaimed = await repository.claim_due(
            now=now + timedelta(minutes=2),
            claimed_until=now + timedelta(minutes=4),
            limit=1,
        )
        assert len(reclaimed) == 1
        retry_at = now + timedelta(minutes=10)
        await repository.release_for_retry(reclaimed[0], available_at=retry_at)
        await session.commit()

        retried = await session.get(PushDeliveryJob, reclaimed[0])
        assert retried.attempt_count == 1
        assert retried.available_at == retry_at
        assert retried.claimed_until is None

        contexts = await repository.get_contexts([job.id for job in jobs])
        assert {context.fcm_token for context in contexts} == {
            "token-jobs-1",
            "token-jobs-2",
        }
        assert {context.establishment_name for context in contexts} == {"Jobs"}
        assert {context.threshold_hours for context in contexts} == {168}

        await StaleEstablishmentCycleRepository(session).delete_pending_jobs(cycle.id)
        await session.commit()
        assert (
            await session.scalar(select(func.count()).select_from(PushDeliveryJob)) == 0
        )
        stored_cycle = await session.get(StaleEstablishmentCycle, cycle.id)
        assert stored_cycle.next_threshold_hours == 336


async def test_notice_consumption_requires_devices_and_advances_only_once(app):
    from app.db.database import AsyncSessionLocal
    from app.db.unit_of_work import UnitOfWork
    from app.services.notifications.stale_establishment_notification_service import (
        StaleEstablishmentNotificationService,
    )

    now = ACTIVATED_AT + timedelta(days=22)
    async with AsyncSessionLocal() as session:
        establishment = _establishment("Consumption")
        worker = _user("consumption")
        session.add_all([establishment, worker])
        await session.flush()
        cycle = await _create_cycle(session, establishment.id)
        await session.commit()
        cycle_id = cycle.id

    service = StaleEstablishmentNotificationService(
        uow_factory=UnitOfWork,
        fcm_client=None,
    )
    await service._consume_due_thresholds(now=now)
    async with AsyncSessionLocal() as session:
        cycle = await session.get(StaleEstablishmentCycle, cycle_id)
        assert cycle.next_threshold_hours == 168
        assert cycle.next_due_at == ACTIVATED_AT + timedelta(hours=168)
        assert (
            await session.scalar(select(func.count()).select_from(PushDeliveryJob)) == 0
        )

        session.add(
            UserEstablishment(
                user_id=worker.id,
                establishment_id=establishment.id,
                status=UserEstablishmentStatus.APPROVED,
            )
        )
        await _create_device(session, worker.id, "consumption")
        await session.commit()

    await service._consume_due_thresholds(now=now)
    async with AsyncSessionLocal() as session:
        cycle = await session.get(StaleEstablishmentCycle, cycle_id)
        assert cycle.next_threshold_hours == 336
        assert cycle.next_due_at == ACTIVATED_AT + timedelta(hours=336)
        jobs = list((await session.scalars(select(PushDeliveryJob))).all())
        assert len(jobs) == 1
        assert jobs[0].threshold_hours == 168


async def test_device_less_due_pages_do_not_starve_a_later_eligible_cycle(app):
    from app.db.database import AsyncSessionLocal
    from app.db.unit_of_work import UnitOfWork
    from app.services.notifications.stale_establishment_notification_service import (
        StaleEstablishmentNotificationService,
    )

    now = ACTIVATED_AT + timedelta(days=22)
    async with AsyncSessionLocal() as session:
        earlier_cycle_ids = []
        for index in range(101):
            establishment = _establishment(f"No devices {index}")
            session.add(establishment)
            await session.flush()
            cycle = await _create_cycle(
                session,
                establishment.id,
                started_at=ACTIVATED_AT - timedelta(days=1),
            )
            earlier_cycle_ids.append(cycle.id)

        eligible_establishment = _establishment("Eligible after page one")
        worker = _user("eligible-after-page-one")
        session.add_all([eligible_establishment, worker])
        await session.flush()
        eligible_cycle = await _create_cycle(session, eligible_establishment.id)
        session.add(
            UserEstablishment(
                user_id=worker.id,
                establishment_id=eligible_establishment.id,
                status=UserEstablishmentStatus.APPROVED,
            )
        )
        device = await _create_device(session, worker.id, "eligible-after-page-one")
        await session.commit()
        eligible_cycle_id = eligible_cycle.id
        device_id = device.id

    service = StaleEstablishmentNotificationService(
        uow_factory=UnitOfWork,
        fcm_client=None,
    )
    await service._consume_due_thresholds(now=now)

    async with AsyncSessionLocal() as session:
        eligible_cycle = await session.get(StaleEstablishmentCycle, eligible_cycle_id)
        assert eligible_cycle.next_threshold_hours == 336
        jobs = list((await session.scalars(select(PushDeliveryJob))).all())
        assert len(jobs) == 1
        assert jobs[0].device_id == device_id
        first_earlier_cycle = await session.get(
            StaleEstablishmentCycle, earlier_cycle_ids[0]
        )
        assert first_earlier_cycle.next_threshold_hours == 168


async def test_guarded_token_rotation_and_database_cascades(app):
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        establishment = _establishment("Cascades")
        user = _user("cascades")
        session.add_all([establishment, user])
        await session.flush()
        device_a = await _create_device(session, user.id, "cascade-a")
        device_b = await _create_device(session, user.id, "cascade-b")
        cycle = await _create_cycle(session, establishment.id)
        jobs = await PushDeliveryJobRepository(session).create_for_devices(
            stale_cycle_id=cycle.id,
            threshold_hours=168,
            device_ids=[device_a.id, device_b.id],
            available_at=ACTIVATED_AT,
        )
        await session.commit()

        claimed_token = device_a.fcm_token
        device_a.fcm_token = "token-cascade-a-rotated"
        await session.commit()
        device_repository = UserPushDeviceRepository(session)
        assert (
            await device_repository.delete_if_token_matches(
                device_id=device_a.id,
                fcm_token=claimed_token,
            )
            == 0
        )
        await PushDeliveryJobRepository(session).delete_by_id(jobs[0].id)
        await session.commit()
        assert await session.get(UserPushDevice, device_a.id) is not None
        assert await session.get(PushDeliveryJob, jobs[0].id) is None

        assert (
            await device_repository.delete_if_token_matches(
                device_id=device_b.id,
                fcm_token=device_b.fcm_token,
            )
            == 1
        )
        await session.commit()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PushDeliveryJob)
                .where(PushDeliveryJob.id == jobs[1].id)
            )
            == 0
        )
        assert await session.get(StaleEstablishmentCycle, cycle.id) is not None

        await session.delete(establishment)
        await session.commit()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(StaleEstablishmentCycle)
                .where(StaleEstablishmentCycle.id == cycle.id)
            )
            == 0
        )
