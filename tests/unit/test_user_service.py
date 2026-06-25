import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.establishment import (
    EstablishmentWithStatusDomain,
    UserEstablishmentStatus,
)
from app.domain.user import ProfileDomain, UserActor, UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    EstablishmentNotFoundError,
    UserNotFoundError,
)
from app.schemas.user_schema import ProfileUpdateRequest
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


def _make_establishment(name="Centro A", formatted_address="Calle 1"):
    establishment = MagicMock()
    establishment.id = uuid.uuid4()
    establishment.name = name
    establishment.formatted_address = formatted_address
    establishment.latitude = -34.6037
    establishment.longitude = -58.3816
    establishment.place_id = f"place-{uuid.uuid4().hex[:8]}"
    establishment.city = "Buenos Aires"
    establishment.province = "Buenos Aires"
    return establishment


def _make_relation(establishment_id, status):
    relation = MagicMock()
    relation.establishment_id = establishment_id
    relation.status = status
    return relation


def _make_uow(
    *, user=None, relations=None, establishments=None, establishments_by_ids=None
):
    uow = AsyncMock()
    uow.user_repo.get_by_id = AsyncMock(return_value=user)
    uow.user_repo.update_profile = AsyncMock()
    uow.user_establishment_repo.get_by_user_id = AsyncMock(
        return_value=relations if relations is not None else []
    )
    uow.user_establishment_repo.preset_relation = AsyncMock()
    uow.user_establishment_repo.update_status_for_ids = AsyncMock()
    uow.establishment_repo.find_by_ids = AsyncMock(return_value=establishments or [])
    uow.establishment_repo.get_all_by_ids = AsyncMock(
        return_value=establishments_by_ids or []
    )
    uow.commit = AsyncMock()
    return uow


def _actor_for(user, *, user_id=None):
    return UserActor(
        user_id=user_id if user_id is not None else user.id, role=user.role
    )


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_manager_with_mixed_status_establishments(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment(name="Centro A", formatted_address="Calle A 123")
        estab_b = _make_establishment(name="Centro B", formatted_address="Calle B 456")
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
        assert first.formatted_address == "Calle A 123"
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
    async def test_analyst_has_none_establishments_and_skips_relation_query(self):
        user = _make_user(role=UserRole.ANALYST)
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
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.ANALYST)

        with pytest.raises(UserNotFoundError):
            await service.get_profile(actor)

    @pytest.mark.asyncio
    async def test_token_user_id_is_used_for_lookup(self):
        user = _make_user(role=UserRole.ANALYST)
        token_user_id = str(uuid.uuid4())
        uow = _make_uow(user=user)
        service = UserService(uow)
        actor = UserActor(user_id=token_user_id, role=UserRole.ANALYST)

        await service.get_profile(actor)

        uow.user_repo.get_by_id.assert_called_once_with(token_user_id)

    @pytest.mark.asyncio
    async def test_relation_with_missing_establishment_is_skipped(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment(name="Centro A", formatted_address="Calle A 123")
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


class TestUpdateProfile:
    @pytest.mark.asyncio
    async def test_both_fields_updated_and_committed(self):
        user = _make_user(role=UserRole.ANALYST)
        uow = _make_uow(user=user)
        service = UserService(uow)

        data = ProfileUpdateRequest(name="Juana", last_name="Perez")
        profile = await service.update_profile(_actor_for(user), data)

        uow.user_repo.update_profile.assert_awaited_once()
        called_id, values = uow.user_repo.update_profile.call_args.args
        assert called_id == user.id
        assert values == {"name": "Juana", "last_name": "Perez"}
        uow.commit.assert_awaited_once()

        assert isinstance(profile, ProfileDomain)
        assert profile.name == "Juana"
        assert profile.last_name == "Perez"
        assert profile.email == user.email
        assert profile.role == user.role
        assert profile.status == user.status
        assert profile.establishments is None

    @pytest.mark.asyncio
    async def test_single_field_only_updates_that_field(self):
        user = _make_user(role=UserRole.ANALYST)
        uow = _make_uow(user=user)
        service = UserService(uow)

        data = ProfileUpdateRequest(name="OnlyName")
        profile = await service.update_profile(_actor_for(user), data)

        _, values = uow.user_repo.update_profile.call_args.args
        assert values == {"name": "OnlyName"}
        assert profile.name == "OnlyName"
        assert profile.last_name == user.last_name

    @pytest.mark.asyncio
    async def test_empty_update_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.ANALYST)
        uow = _make_uow(user=user)
        service = UserService(uow)

        with pytest.raises(EmptyUpdateRequestError):
            await service.update_profile(_actor_for(user), ProfileUpdateRequest())

        uow.user_repo.update_profile.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        uow = _make_uow(user=None)
        service = UserService(uow)
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.ANALYST)

        with pytest.raises(UserNotFoundError):
            await service.update_profile(actor, ProfileUpdateRequest(name="X"))

        uow.user_repo.update_profile.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_manager_response_includes_status_annotated_establishments(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment(name="Centro A", formatted_address="Calle A 123")
        relations = [_make_relation(estab_a.id, UserEstablishmentStatus.APPROVED)]
        uow = _make_uow(user=user, relations=relations, establishments=[estab_a])
        service = UserService(uow)

        profile = await service.update_profile(
            _actor_for(user), ProfileUpdateRequest(name="New")
        )

        assert profile.establishments is not None
        assert len(profile.establishments) == 1
        assert profile.establishments[0].id == estab_a.id
        assert profile.establishments[0].status == UserEstablishmentStatus.APPROVED

    @pytest.mark.asyncio
    async def test_token_user_id_is_used_for_lookup(self):
        user = _make_user(role=UserRole.ANALYST)
        token_user_id = str(uuid.uuid4())
        uow = _make_uow(user=user)
        service = UserService(uow)
        actor = UserActor(user_id=token_user_id, role=UserRole.ANALYST)

        await service.update_profile(actor, ProfileUpdateRequest(name="X"))

        uow.user_repo.get_by_id.assert_called_once_with(token_user_id)
        # The update targets the loaded user's own id, not the raw token value.
        called_id, _ = uow.user_repo.update_profile.call_args.args
        assert called_id == user.id


class TestGetOwnEstablishments:
    @pytest.mark.asyncio
    async def test_manager_with_mixed_status_relations(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment(name="Centro A", formatted_address="Calle A")
        estab_b = _make_establishment(name="Centro B", formatted_address="Calle B")
        relations = [
            _make_relation(estab_a.id, UserEstablishmentStatus.APPROVED),
            _make_relation(estab_b.id, UserEstablishmentStatus.REJECTED),
        ]
        uow = _make_uow(
            user=user, relations=relations, establishments=[estab_a, estab_b]
        )
        service = UserService(uow)

        result = await service.get_own_establishments(_actor_for(user))

        assert len(result) == 2
        assert all(isinstance(r, EstablishmentWithStatusDomain) for r in result)
        by_id = {r.id: r for r in result}
        assert by_id[estab_a.id].name == "Centro A"
        assert by_id[estab_a.id].formatted_address == "Calle A"
        assert by_id[estab_a.id].status == UserEstablishmentStatus.APPROVED
        assert by_id[estab_b.id].status == UserEstablishmentStatus.REJECTED

    @pytest.mark.asyncio
    async def test_no_relations_returns_empty_list(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        uow = _make_uow(user=user, relations=[])
        service = UserService(uow)

        result = await service.get_own_establishments(_actor_for(user))

        assert result == []
        uow.establishment_repo.find_by_ids.assert_not_called()


class TestRequestEstablishmentAccess:
    @pytest.mark.asyncio
    async def test_new_ids_are_inserted_as_pending(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab_a = _make_establishment()
        estab_b = _make_establishment()
        uow = _make_uow(
            user=user, relations=[], establishments_by_ids=[estab_a, estab_b]
        )
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab_a.id, estab_b.id]
        )

        assert uow.user_establishment_repo.preset_relation.await_count == 2
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_awaited_once()
        assert {r.id for r in result} == {estab_a.id, estab_b.id}
        assert all(r.status == UserEstablishmentStatus.PENDING for r in result)

    @pytest.mark.asyncio
    async def test_rejected_id_is_re_requested(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, UserEstablishmentStatus.REJECTED)]
        uow = _make_uow(user=user, relations=relations, establishments_by_ids=[estab])
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab.id]
        )

        uow.user_establishment_repo.update_status_for_ids.assert_awaited_once()
        _, ids, new_status = (
            uow.user_establishment_repo.update_status_for_ids.call_args.args
        )
        assert ids == [estab.id]
        assert new_status == UserEstablishmentStatus.PENDING
        uow.user_establishment_repo.preset_relation.assert_not_called()
        assert result[0].status == UserEstablishmentStatus.PENDING

    @pytest.mark.asyncio
    async def test_approved_id_is_untouched(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, UserEstablishmentStatus.APPROVED)]
        uow = _make_uow(user=user, relations=relations, establishments_by_ids=[estab])
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab.id]
        )

        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        assert result[0].status == UserEstablishmentStatus.APPROVED

    @pytest.mark.asyncio
    async def test_pending_id_is_untouched(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, UserEstablishmentStatus.PENDING)]
        uow = _make_uow(user=user, relations=relations, establishments_by_ids=[estab])
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab.id]
        )

        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        assert result[0].status == UserEstablishmentStatus.PENDING

    @pytest.mark.asyncio
    async def test_mixed_batch_classifies_each_id(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        approved = _make_establishment()
        rejected = _make_establishment()
        new = _make_establishment()
        relations = [
            _make_relation(approved.id, UserEstablishmentStatus.APPROVED),
            _make_relation(rejected.id, UserEstablishmentStatus.REJECTED),
        ]
        uow = _make_uow(
            user=user,
            relations=relations,
            establishments_by_ids=[approved, rejected, new],
        )
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [approved.id, rejected.id, new.id]
        )

        uow.user_establishment_repo.update_status_for_ids.assert_awaited_once()
        _, repend_ids, _ = (
            uow.user_establishment_repo.update_status_for_ids.call_args.args
        )
        assert repend_ids == [rejected.id]
        uow.user_establishment_repo.preset_relation.assert_awaited_once_with(
            user.id, new.id
        )
        by_id = {r.id: r for r in result}
        assert by_id[approved.id].status == UserEstablishmentStatus.APPROVED
        assert by_id[rejected.id].status == UserEstablishmentStatus.PENDING
        assert by_id[new.id].status == UserEstablishmentStatus.PENDING

    @pytest.mark.asyncio
    async def test_duplicate_ids_are_deduplicated(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab = _make_establishment()
        uow = _make_uow(user=user, relations=[], establishments_by_ids=[estab])
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab.id, estab.id]
        )

        assert uow.user_establishment_repo.preset_relation.await_count == 1
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_unknown_establishment_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        uow = _make_uow(user=user, relations=[])
        uow.establishment_repo.get_all_by_ids = AsyncMock(
            side_effect=EstablishmentNotFoundError(str(uuid.uuid4()))
        )
        service = UserService(uow)

        with pytest.raises(EstablishmentNotFoundError):
            await service.request_establishment_access(_actor_for(user), [uuid.uuid4()])

        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_not_called()
