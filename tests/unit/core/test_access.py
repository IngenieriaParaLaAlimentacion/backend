import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import EstablishmentAccessDeniedError
from app.services.access import (
    check_characterization_edit_access,
    check_field_work_access,
)


def _make_uow(*, relation_status=None, approved_ids=()):
    uow = AsyncMock()
    relation = None
    if relation_status is not None:
        relation = MagicMock(status=relation_status)
    uow.user_establishment_repo.get_relation = AsyncMock(return_value=relation)
    uow.user_establishment_repo.get_approved_establishment_ids = AsyncMock(
        return_value=set(approved_ids)
    )
    return uow


def _actor(role):
    return UserActor(user_id=uuid.uuid4(), role=role)


class TestCheckFieldWorkAccess:
    @pytest.mark.parametrize(
        "role", [UserRole.FIELD_WORKER, UserRole.ADMIN, UserRole.SUPERADMIN]
    )
    @pytest.mark.parametrize("establishment_id", [None, uuid.uuid4()])
    async def test_other_roles_are_allowed_without_a_relation(
        self, role, establishment_id
    ):
        """Field work is theirs by role, so no relation is required."""
        await check_field_work_access(_make_uow(), _actor(role), establishment_id)

    async def test_analyst_approved_on_the_establishment_is_allowed(self):
        uow = _make_uow(relation_status=UserEstablishmentStatus.APPROVED)
        await check_field_work_access(uow, _actor(UserRole.ANALYST), uuid.uuid4())

    @pytest.mark.parametrize(
        "relation_status",
        [
            None,
            UserEstablishmentStatus.PENDING,
            UserEstablishmentStatus.REJECTED,
            UserEstablishmentStatus.REVOKED,
            UserEstablishmentStatus.WITHDRAWN,
        ],
    )
    async def test_analyst_not_approved_on_the_establishment_is_denied(
        self, relation_status
    ):
        """A pending, rejected or dropped link grants no field work."""
        # Approved elsewhere must not leak into this establishment.
        uow = _make_uow(relation_status=relation_status, approved_ids=[uuid.uuid4()])
        with pytest.raises(EstablishmentAccessDeniedError):
            await check_field_work_access(uow, _actor(UserRole.ANALYST), uuid.uuid4())

    @pytest.mark.parametrize(
        ("approved_ids", "allowed"), [([uuid.uuid4()], True), ([], False)]
    )
    async def test_analyst_without_establishment_needs_any_approved_link(
        self, approved_ids, allowed
    ):
        """Work that names no establishment requires approval somewhere."""
        uow = _make_uow(approved_ids=approved_ids)
        if allowed:
            await check_field_work_access(uow, _actor(UserRole.ANALYST), None)
        else:
            with pytest.raises(EstablishmentAccessDeniedError):
                await check_field_work_access(uow, _actor(UserRole.ANALYST), None)


class TestCheckCharacterizationEditAccess:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPERADMIN])
    async def test_admins_are_allowed_without_a_relation(self, role):
        await check_characterization_edit_access(
            _make_uow(), _actor(role), uuid.uuid4()
        )

    async def test_field_worker_approved_on_the_establishment_is_allowed(self):
        uow = _make_uow(relation_status=UserEstablishmentStatus.APPROVED)
        await check_characterization_edit_access(
            uow, _actor(UserRole.FIELD_WORKER), uuid.uuid4()
        )

    @pytest.mark.parametrize(
        ("role", "relation_status"),
        [
            (UserRole.FIELD_WORKER, None),
            (UserRole.FIELD_WORKER, UserEstablishmentStatus.PENDING),
            (UserRole.FIELD_WORKER, UserEstablishmentStatus.REVOKED),
            # An approved analyst may read the establishment, not edit its profile.
            (UserRole.ANALYST, UserEstablishmentStatus.APPROVED),
        ],
    )
    async def test_others_are_denied(self, role, relation_status):
        uow = _make_uow(relation_status=relation_status)
        with pytest.raises(EstablishmentAccessDeniedError):
            await check_characterization_edit_access(uow, _actor(role), uuid.uuid4())
