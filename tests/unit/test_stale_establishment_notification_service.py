import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest

from app.exceptions.domain_exceptions import NotificationConfigurationError
from app.services.notifications.fcm_client import FcmOutcome, FcmResult
from app.services.notifications.stale_establishment_notification_service import (
    StaleEstablishmentNotificationService,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


class FakeUow:
    def __init__(self, **repositories):
        self.__dict__.update(repositories)
        self.commit = AsyncMock()
        self.active = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.active = False
        return None


class UowFactory:
    def __init__(self, *uows):
        self.uows = list(uows)

    def __call__(self):
        return self.uows.pop(0)


def _service(factory, fcm=object(), clock=lambda: NOW):
    return StaleEstablishmentNotificationService(factory, fcm, clock=clock)


def _fcm(*, send):
    return SimpleNamespace(
        start=AsyncMock(),
        send=send,
        aclose=AsyncMock(),
    )


async def test_missing_fcm_configuration_is_rejected():
    service = StaleEstablishmentNotificationService(lambda: None, None)
    with pytest.raises(NotificationConfigurationError):
        await service.run(NOW)


async def test_cycle_starts_at_latest_activity_and_is_due_after_exact_168_hours():
    establishment_id = uuid4()
    latest = NOW - timedelta(days=90)
    repo = SimpleNamespace(
        list_activity_advances=AsyncMock(
            return_value=[
                SimpleNamespace(
                    establishment_id=establishment_id, last_outflow_at=latest
                )
            ]
        ),
        get_for_update=AsyncMock(return_value=None),
        create_if_absent=AsyncMock(
            return_value=SimpleNamespace(last_outflow_at=latest)
        ),
    )
    uow = FakeUow(stale_cycle_repo=repo)

    await _service(UowFactory(uow))._synchronize_cycles()

    assert repo.create_if_absent.await_args.kwargs["started_at"] == latest
    assert repo.create_if_absent.await_args.kwargs["next_due_at"] == latest + timedelta(
        hours=168
    )
    uow.commit.assert_awaited_once()


async def test_no_outflow_advances_creates_no_cycles():
    repo = SimpleNamespace(
        list_activity_advances=AsyncMock(return_value=[]),
        get_for_update=AsyncMock(),
        create_if_absent=AsyncMock(),
    )
    uow = FakeUow(stale_cycle_repo=repo)

    await _service(UowFactory(uow))._synchronize_cycles()

    repo.get_for_update.assert_not_awaited()
    repo.create_if_absent.assert_not_awaited()
    uow.commit.assert_awaited_once()


async def test_newer_activity_cancels_jobs_and_resets_cycle():
    establishment_id = uuid4()
    cycle = SimpleNamespace(
        id=uuid4(),
        last_outflow_at=NOW - timedelta(days=2),
        started_at=NOW - timedelta(days=2),
        next_threshold_hours=336,
        next_due_at=NOW + timedelta(days=12),
    )
    latest = NOW
    repo = SimpleNamespace(
        list_activity_advances=AsyncMock(
            return_value=[
                SimpleNamespace(
                    establishment_id=establishment_id, last_outflow_at=latest
                )
            ]
        ),
        get_for_update=AsyncMock(return_value=cycle),
        delete_pending_jobs=AsyncMock(),
    )

    await _service(UowFactory(FakeUow(stale_cycle_repo=repo)))._synchronize_cycles()

    repo.delete_pending_jobs.assert_awaited_once_with(cycle.id)
    assert cycle.last_outflow_at == latest
    assert cycle.next_threshold_hours == 168
    assert cycle.next_due_at == NOW + timedelta(hours=168)


async def test_concurrent_first_insert_reloads_equal_winner_without_reset():
    establishment_id = uuid4()
    existing = SimpleNamespace(last_outflow_at=NOW)
    repo = SimpleNamespace(
        list_activity_advances=AsyncMock(
            return_value=[
                SimpleNamespace(establishment_id=establishment_id, last_outflow_at=NOW)
            ]
        ),
        get_for_update=AsyncMock(side_effect=[None, existing]),
        create_if_absent=AsyncMock(return_value=None),
        delete_pending_jobs=AsyncMock(),
    )

    await _service(UowFactory(FakeUow(stale_cycle_repo=repo)))._synchronize_cycles()

    assert repo.get_for_update.await_count == 2
    repo.delete_pending_jobs.assert_not_awaited()


async def test_zero_devices_does_not_consume_threshold():
    cycle = SimpleNamespace(
        id=uuid4(),
        establishment_id=uuid4(),
        started_at=NOW - timedelta(days=14),
        next_threshold_hours=168,
        next_due_at=NOW,
    )
    jobs = SimpleNamespace(create_for_devices=AsyncMock())
    uow = FakeUow(
        stale_cycle_repo=SimpleNamespace(
            list_due_for_update=AsyncMock(return_value=[cycle])
        ),
        push_device_repo=SimpleNamespace(
            list_eligible_for_establishment=AsyncMock(return_value=[])
        ),
        push_delivery_job_repo=jobs,
    )

    await _service(UowFactory(uow))._consume_due_thresholds(now=NOW)

    jobs.create_for_devices.assert_not_awaited()
    assert cycle.next_threshold_hours == 168
    assert cycle.next_due_at == NOW


@pytest.mark.parametrize(
    ("current", "following"), [(168, 336), (336, 504), (504, None)]
)
async def test_consumption_creates_jobs_and_advances_one_threshold(current, following):
    cycle = SimpleNamespace(
        id=uuid4(),
        establishment_id=uuid4(),
        started_at=NOW - timedelta(days=30),
        next_threshold_hours=current,
        next_due_at=NOW,
    )
    devices = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    jobs = SimpleNamespace(create_for_devices=AsyncMock())
    uow = FakeUow(
        stale_cycle_repo=SimpleNamespace(
            list_due_for_update=AsyncMock(return_value=[cycle])
        ),
        push_device_repo=SimpleNamespace(
            list_eligible_for_establishment=AsyncMock(return_value=devices)
        ),
        push_delivery_job_repo=jobs,
    )

    await _service(UowFactory(uow))._consume_due_thresholds(now=NOW)

    jobs.create_for_devices.assert_awaited_once_with(
        stale_cycle_id=cycle.id,
        threshold_hours=current,
        device_ids=[device.id for device in devices],
        available_at=NOW,
    )
    assert cycle.next_threshold_hours == following
    assert cycle.next_due_at == (
        None if following is None else cycle.started_at + timedelta(hours=following)
    )


async def test_claim_commits_lease_before_hydrating_contexts():
    events = []
    job_id = uuid4()
    claim = AsyncMock(side_effect=lambda **kwargs: events.append("claim") or [job_id])
    commit = AsyncMock(side_effect=lambda: events.append("commit"))
    contexts = AsyncMock(side_effect=lambda ids: events.append("hydrate") or [object()])
    claim_uow = FakeUow(push_delivery_job_repo=SimpleNamespace(claim_due=claim))
    claim_uow.commit = commit
    hydrate_uow = FakeUow(push_delivery_job_repo=SimpleNamespace(get_contexts=contexts))

    await _service(UowFactory(claim_uow, hydrate_uow))._claim(NOW, 10)

    assert events == ["claim", "commit", "hydrate"]


async def test_empty_claim_does_not_open_hydration_uow():
    claim_uow = FakeUow(
        push_delivery_job_repo=SimpleNamespace(claim_due=AsyncMock(return_value=[]))
    )
    factory = UowFactory(claim_uow)

    assert await _service(factory)._claim(NOW, 10) == []
    assert factory.uows == []
    claim_uow.commit.assert_awaited_once()


@pytest.mark.parametrize("attempt", [1, 2, 20])
async def test_transient_release_uses_exponential_backoff_capped_at_six_hours(
    attempt,
):
    job = SimpleNamespace(job_id=uuid4(), attempt_count=attempt)
    release = AsyncMock()
    uow = FakeUow(push_delivery_job_repo=SimpleNamespace(release_for_retry=release))

    await _service(UowFactory(uow))._finish(job, FcmOutcome.TRANSIENT, NOW)

    expected = min(60 * (2 ** (attempt - 1)), 6 * 60 * 60)
    release.assert_awaited_once_with(
        job.job_id, available_at=NOW + timedelta(seconds=expected)
    )


async def test_permanent_token_uses_guarded_eviction_then_idempotent_job_delete():
    job = SimpleNamespace(job_id=uuid4(), device_id=uuid4(), fcm_token="token-a")
    evict = AsyncMock()
    delete = AsyncMock()
    uow = FakeUow(
        push_device_repo=SimpleNamespace(delete_if_token_matches=evict),
        push_delivery_job_repo=SimpleNamespace(delete_by_id=delete),
    )

    await _service(UowFactory(uow))._finish(job, FcmOutcome.PERMANENT_TOKEN, NOW)

    evict.assert_awaited_once_with(device_id=job.device_id, fcm_token="token-a")
    delete.assert_awaited_once_with(job.job_id)


async def test_permanent_message_deletes_job_without_evicting_device():
    job = SimpleNamespace(job_id=uuid4())
    delete = AsyncMock()
    device_repo = SimpleNamespace(delete_if_token_matches=AsyncMock())
    uow = FakeUow(
        push_device_repo=device_repo,
        push_delivery_job_repo=SimpleNamespace(delete_by_id=delete),
    )

    await _service(UowFactory(uow))._finish(job, FcmOutcome.PERMANENT_MESSAGE, NOW)

    delete.assert_awaited_once_with(job.job_id)
    device_repo.delete_if_token_matches.assert_not_awaited()


async def test_message_and_payload_contract():
    establishment_id = uuid4()
    job = SimpleNamespace(
        job_id=uuid4(),
        device_id=uuid4(),
        fcm_token="token",
        establishment_id=establishment_id,
        threshold_hours=336,
        attempt_count=0,
    )
    fcm = _fcm(send=AsyncMock(return_value=FcmResult(FcmOutcome.SUCCESS)))
    service = _service(lambda: None, fcm=fcm)
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    service._claim = AsyncMock(side_effect=[[job], []])
    service._finish = AsyncMock()

    await service.run(NOW)

    fcm.send.assert_awaited_once_with(
        token="token",
        title="Hace 14 días que no se registran salidas",
        body="Registrá una salida para mantener actualizado el stock.",
        data={
            "type": "stale_establishment",
            "establishment_id": str(establishment_id),
            "stale_days": "14",
        },
        collapse_key=f"stale-establishment:{establishment_id}",
    )
    service._finish.assert_awaited_once_with(job, FcmOutcome.SUCCESS, NOW)
    fcm.start.assert_awaited_once_with()
    fcm.aclose.assert_awaited_once_with()


async def test_unexpected_provider_error_is_isolated_as_transient():
    job = SimpleNamespace(
        job_id=uuid4(),
        device_id=uuid4(),
        fcm_token="token",
        establishment_id=uuid4(),
        threshold_hours=168,
        attempt_count=0,
    )
    fcm = _fcm(send=AsyncMock(side_effect=RuntimeError("provider")))
    service = _service(lambda: None, fcm=fcm)
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    service._claim = AsyncMock(side_effect=[[job], []])
    service._finish = AsyncMock()

    await service.run(NOW)

    service._finish.assert_awaited_once_with(job, FcmOutcome.TRANSIENT, NOW)


async def test_claims_fresh_waves_of_ten_after_prior_wave_is_finalized():
    jobs = [
        SimpleNamespace(
            job_id=uuid4(),
            fcm_token=f"token-{index}",
            establishment_id=uuid4(),
            threshold_hours=168,
            attempt_count=0,
        )
        for index in range(12)
    ]
    times = iter(
        [
            NOW + timedelta(seconds=1),
            *[NOW + timedelta(seconds=2)] * 10,
            NOW + timedelta(seconds=3),
            *[NOW + timedelta(seconds=4)] * 2,
            NOW + timedelta(seconds=5),
        ]
    )
    fcm = _fcm(send=AsyncMock(return_value=FcmResult(FcmOutcome.SUCCESS)))
    service = _service(lambda: None, fcm=fcm, clock=lambda: next(times))
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    events = []

    async def claim_jobs(claimed_at, limit):
        events.append(("claim", claimed_at, limit))
        if len([event for event in events if event[0] == "claim"]) == 1:
            return jobs[:10]
        if len([event for event in events if event[0] == "claim"]) == 2:
            assert events[-2][0] == "finish"
            return jobs[10:]
        return []

    async def finish_job(job, outcome, finished_at):
        events.append(("finish", finished_at, job.job_id))

    service._claim = AsyncMock(side_effect=claim_jobs)
    service._finish = AsyncMock(side_effect=finish_job)

    await service.run(NOW)

    assert service._claim.await_args_list == [
        call(NOW + timedelta(seconds=1), 10),
        call(NOW + timedelta(seconds=3), 10),
        call(NOW + timedelta(seconds=5), 10),
    ]
    assert fcm.send.await_count == 12
    fcm.aclose.assert_awaited_once_with()


async def test_ten_provider_sends_are_in_flight_together():
    jobs = [
        SimpleNamespace(
            job_id=uuid4(),
            fcm_token=f"token-{index}",
            establishment_id=uuid4(),
            threshold_hours=168,
            attempt_count=0,
        )
        for index in range(10)
    ]
    all_started = asyncio.Event()
    release = asyncio.Event()
    in_flight = 0

    async def send(**kwargs):
        nonlocal in_flight
        in_flight += 1
        if in_flight == 10:
            all_started.set()
        await release.wait()
        return FcmResult(FcmOutcome.SUCCESS)

    fcm = _fcm(send=AsyncMock(side_effect=send))
    service = _service(lambda: None, fcm=fcm)
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    service._claim = AsyncMock(side_effect=[jobs, []])
    service._finish = AsyncMock()

    run = asyncio.create_task(service.run(NOW))
    await asyncio.wait_for(all_started.wait(), timeout=1)
    assert service._finish.await_count == 0
    release.set()
    await run

    assert service._finish.await_count == 10


async def test_retry_uses_actual_finalization_time():
    job = SimpleNamespace(job_id=uuid4(), attempt_count=1)
    release = AsyncMock()
    uow = FakeUow(push_delivery_job_repo=SimpleNamespace(release_for_retry=release))
    finished_at = NOW + timedelta(minutes=7)

    await _service(UowFactory(uow))._finish(job, FcmOutcome.TRANSIENT, finished_at)

    release.assert_awaited_once_with(
        job.job_id, available_at=finished_at + timedelta(minutes=1)
    )


async def test_no_uow_is_open_while_provider_send_is_blocked():
    job_id = uuid4()
    job = SimpleNamespace(
        job_id=job_id,
        fcm_token="token",
        establishment_id=uuid4(),
        threshold_hours=168,
        attempt_count=0,
    )
    claim_uow = FakeUow(
        push_delivery_job_repo=SimpleNamespace(
            claim_due=AsyncMock(return_value=[job_id])
        )
    )
    hydrate_uow = FakeUow(
        push_delivery_job_repo=SimpleNamespace(
            get_contexts=AsyncMock(return_value=[job])
        )
    )
    empty_uow = FakeUow(
        push_delivery_job_repo=SimpleNamespace(claim_due=AsyncMock(return_value=[]))
    )
    send_started = asyncio.Event()
    release = asyncio.Event()

    async def send(**kwargs):
        assert not claim_uow.active
        assert not hydrate_uow.active
        send_started.set()
        await release.wait()
        return FcmResult(FcmOutcome.SUCCESS)

    fcm = _fcm(send=AsyncMock(side_effect=send))
    service = _service(UowFactory(claim_uow, hydrate_uow, empty_uow), fcm=fcm)
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    service._finish = AsyncMock()

    run = asyncio.create_task(service.run(NOW))
    await asyncio.wait_for(send_started.wait(), timeout=1)
    release.set()
    await run


async def test_one_provider_failure_does_not_cancel_other_nine_sends():
    jobs = [
        SimpleNamespace(
            job_id=uuid4(),
            fcm_token=f"token-{index}",
            establishment_id=uuid4(),
            threshold_hours=168,
            attempt_count=0,
        )
        for index in range(10)
    ]
    completed = []

    async def send(*, token, **kwargs):
        await asyncio.sleep(0)
        if token == "token-0":
            raise RuntimeError("provider")
        completed.append(token)
        return FcmResult(FcmOutcome.SUCCESS)

    fcm = _fcm(send=AsyncMock(side_effect=send))
    service = _service(lambda: None, fcm=fcm)
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    service._claim = AsyncMock(side_effect=[jobs, []])
    service._finish = AsyncMock()

    await service.run(NOW)

    assert len(completed) == 9
    outcomes = {
        args.args[0].fcm_token: args.args[1]
        for args in service._finish.await_args_list
    }
    assert outcomes["token-0"] == FcmOutcome.TRANSIENT
    assert all(
        outcomes[f"token-{index}"] == FcmOutcome.SUCCESS
        for index in range(1, 10)
    )


async def test_run_never_processes_more_than_500_jobs():
    job = SimpleNamespace(
        job_id=uuid4(),
        fcm_token="token",
        establishment_id=uuid4(),
        threshold_hours=168,
        attempt_count=0,
    )
    fcm = _fcm(send=AsyncMock(return_value=FcmResult(FcmOutcome.SUCCESS)))
    service = _service(lambda: None, fcm=fcm)
    service._synchronize_cycles = AsyncMock()
    service._consume_due_thresholds = AsyncMock()
    service._claim = AsyncMock(return_value=[job] * 10)
    service._finish = AsyncMock()

    await service.run(NOW)

    assert service._claim.await_count == 50
    assert all(args.args[1] == 10 for args in service._claim.await_args_list)
    assert fcm.send.await_count == 500
