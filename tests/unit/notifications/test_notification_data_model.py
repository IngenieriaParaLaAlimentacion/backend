from app.models.notifications.push_delivery_job import PushDeliveryJob
from app.models.notifications.stale_establishment_cycle import (
    StaleEstablishmentCycle,
)


def test_stale_cycle_is_one_per_establishment():
    names = {
        constraint.name for constraint in StaleEstablishmentCycle.__table__.constraints
    }
    assert "uq_stale_establishment_cycles_establishment_id" in names


def test_delivery_jobs_have_retry_and_lease_state_only():
    assert {
        "available_at",
        "claimed_until",
        "attempt_count",
    } <= set(PushDeliveryJob.__table__.c.keys())
    assert "last_error" not in PushDeliveryJob.__table__.c
