import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.establishment import (
    EstablishmentWithStatusDomain,
    UserEstablishmentStatus,
)
from app.domain.user import ProfileDomain, UserActor, UserRole, UserStatus
from app.exceptions.domain_exceptions import UserNotFoundError
from app.services.user_service import UserService


def _make_user(
    *,
    role=UserRole.ESTABLISHMENT_MANAGER,
    status=UserStatus.ACTIVE,
):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    user.name = "Test"
    user.last_name = "User"
    user.role = role
    user.status = status
    return user


def _make_establishment(name="Centro A", address="Calle 1"):
    establishment = MagicMock()
    establishment.id = uuid.uuid4()
    establishment.name = name
    establishment.address = address
    return establishment


def _make_relation(establishment_id, status):
    relation = MagicMock()
    relation.establishment_id = establishment_id
    relation.status = status
    return relation


def _make_uow(*, user=None, relations=None, establishments=None):
    uow = AsyncMock()
    uow.user_repo.get_by_id = AsyncMock(return_value=user)
    uow.user_establishment_repo.get_by_user_id = AsyncMock(
        return_value=relations if relations is not None else []
    )
    uow.establishment_repo.find_by_ids = AsyncMock(return_value=establishments or [])
    return uow


def _actor_for(user, *, user_id=None):
    return UserActor(
        user_id=user_id if user_id is not None else user.id, role=user.role
    )


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_manager_with_mixed_status_establishments(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment(name="Centro A", address="Calle A 123")
        estab_b = _make_establishment(name="Centro B", address="Calle B 456")
        relations = [
            _make_relation(estab_a.id, UserEstablishmentStatus.APPROVED),
            _make_relation(estab_b.id, UserEstablishmentStatus.PENDING),
        ]
        uow = _make_uow(
            user=user, relations=relations, establishments=[estab_a, estab_b]
        )
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert isinstance(profile, ProfileDomain)
        assert profile.id == user.id
        assert profile.email == user.email
        assert profile.role == user.role
        assert profile.establishments is not None
        assert len(profile.establishments) == 2

        first, second = profile.establishments
        assert isinstance(first, EstablishmentWithStatusDomain)
        assert first.id == estab_a.id
        assert first.name == "Centro A"
        assert first.address == "Calle A 123"
        assert first.status == UserEstablishmentStatus.APPROVED
        assert second.id == estab_b.id
        assert second.status == UserEstablishmentStatus.PENDING

    @pytest.mark.asyncio
    async def test_manager_with_no_relations_returns_empty_list(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        uow = _make_uow(user=user, relations=[])
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert profile.establishments == []
        uow.establishment_repo.find_by_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_professional_has_none_establishments_and_skips_relation_query(self):
        user = _make_user(role=UserRole.PROFESSIONAL)
        uow = _make_uow(user=user)
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert profile.establishments is None
        uow.user_establishment_repo.get_by_user_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_has_none_establishments(self):
        user = _make_user(role=UserRole.ADMIN)
        uow = _make_uow(user=user)
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert profile.establishments is None
        uow.user_establishment_repo.get_by_user_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        uow = _make_uow(user=None)
        service = UserService(uow)
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.PROFESSIONAL)

        with pytest.raises(UserNotFoundError):
            await service.get_profile(actor)

    @pytest.mark.asyncio
    async def test_string_user_id_is_converted_to_uuid(self):
        user = _make_user(role=UserRole.PROFESSIONAL)
        token_user_id = uuid.uuid4()
        uow = _make_uow(user=user)
        service = UserService(uow)
        actor = UserActor(user_id=str(token_user_id), role=UserRole.PROFESSIONAL)

        await service.get_profile(actor)

        uow.user_repo.get_by_id.assert_called_once_with(token_user_id)
        (called_id,), _ = uow.user_repo.get_by_id.call_args
        assert isinstance(called_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_relation_with_missing_establishment_is_skipped(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment(name="Centro A", address="Calle A 123")
        missing_establishment_id = uuid.uuid4()
        relations = [
            _make_relation(estab_a.id, UserEstablishmentStatus.APPROVED),
            _make_relation(missing_establishment_id, UserEstablishmentStatus.PENDING),
        ]
        uow = _make_uow(user=user, relations=relations, establishments=[estab_a])
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert profile.establishments is not None
        assert len(profile.establishments) == 1
        assert profile.establishments[0].id == estab_a.id
