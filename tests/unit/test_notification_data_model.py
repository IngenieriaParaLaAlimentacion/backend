from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.notifications.push_delivery_job import PushDeliveryJob
from app.models.notifications.stale_establishment_cycle import (
    StaleEstablishmentCycle,
)
from app.models.notifications.user_push_device import UserPushDevice


def test_push_registration_identity_is_unique():
    names = {constraint.name for constraint in UserPushDevice.__table__.constraints}
    assert "uq_user_push_devices_installation_id" in names
    assert "uq_user_push_devices_fcm_token" in names


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


def test_notification_migration_is_linear_off_current_head():
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision("f4b8c2d91e06")
    assert migration.down_revision == "a1c6b8d47e02"
    assert scripts.get_heads() == ["f4b8c2d91e06"]
