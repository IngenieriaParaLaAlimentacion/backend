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
    EstablishmentAlreadySubscribedError,
    EstablishmentNotFoundError,
    RoleNotAllowedError,
    UniqueConstraintError,
    UserEstablishmentNotFoundError,
    UserEstablishmentNotWithdrawableError,
    UserNotFoundError,
)
from app.schemas.auth.user_schema import ProfileUpdateRequest
from app.services.auth.user_service import UserService


def _make_user(
    *,
    role=UserRole.FIELD_WORKER,
    status=UserStatus.ACTIVE,
):
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
    uow.user_establishment_repo.get_relation = AsyncMock(return_value=None)
    uow.user_establishment_repo.create_or_approve_relation = AsyncMock()
    uow.user_establishment_repo.delete_relation = AsyncMock(return_value=True)
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
    async def test_field_worker_with_mixed_status_establishments(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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

    async def test_field_worker_with_no_relations_returns_empty_list(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
        uow = _make_uow(user=user, relations=[])
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert profile.establishments == []
        uow.establishment_repo.find_by_ids.assert_not_called()

    @pytest.mark.parametrize("role", [UserRole.ANALYST, UserRole.ADMIN])
    async def test_non_field_worker_lists_own_establishments(self, role):
        """An admin or analyst linked to an establishment sees it in the profile."""
        user = _make_user(role=role)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, UserEstablishmentStatus.APPROVED)]
        uow = _make_uow(user=user, relations=relations, establishments=[estab])
        service = UserService(uow)

        profile = await service.get_profile(_actor_for(user))

        assert [(e.id, e.status) for e in profile.establishments] == [
            (estab.id, UserEstablishmentStatus.APPROVED)
        ]

    async def test_user_not_found_raises(self):
        uow = _make_uow(user=None)
        service = UserService(uow)
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.ANALYST)

        with pytest.raises(UserNotFoundError):
            await service.get_profile(actor)

    async def test_token_user_id_is_used_for_lookup(self):
        user = _make_user(role=UserRole.ANALYST)
        token_user_id = str(uuid.uuid4())
        uow = _make_uow(user=user)
        service = UserService(uow)
        actor = UserActor(user_id=token_user_id, role=UserRole.ANALYST)

        await service.get_profile(actor)

        uow.user_repo.get_by_id.assert_called_once_with(token_user_id)

    async def test_relation_with_missing_establishment_is_skipped(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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
        assert profile.establishments == []

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

    async def test_empty_update_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.ANALYST)
        uow = _make_uow(user=user)
        service = UserService(uow)

        with pytest.raises(EmptyUpdateRequestError):
            await service.update_profile(_actor_for(user), ProfileUpdateRequest())

        uow.user_repo.update_profile.assert_not_called()
        uow.commit.assert_not_called()

    async def test_user_not_found_raises(self):
        uow = _make_uow(user=None)
        service = UserService(uow)
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.ANALYST)

        with pytest.raises(UserNotFoundError):
            await service.update_profile(actor, ProfileUpdateRequest(name="X"))

        uow.user_repo.update_profile.assert_not_called()
        uow.commit.assert_not_called()

    async def test_field_worker_response_includes_status_annotated_establishments(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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
        assert profile.description is None

    async def test_unset_optional_fields_fall_back_to_existing_values(self):
        user = _make_user(role=UserRole.ANALYST)
        user.locality = "Existing locality"
        uow = _make_uow(user=user)
        service = UserService(uow)

        data = ProfileUpdateRequest(name="New Name")
        profile = await service.update_profile(_actor_for(user), data)

        assert profile.locality == "Existing locality"
        assert profile.description is None
        assert profile.contact_phone is None


class TestGetOwnEstablishments:
    async def test_field_worker_with_mixed_status_relations(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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

    async def test_no_relations_returns_empty_list(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
        uow = _make_uow(user=user, relations=[])
        service = UserService(uow)

        result = await service.get_own_establishments(_actor_for(user))

        assert result == []
        uow.establishment_repo.find_by_ids.assert_not_called()


class TestRequestEstablishmentAccess:
    async def test_new_ids_are_inserted_as_pending(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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

    @pytest.mark.parametrize(
        "status",
        [
            UserEstablishmentStatus.REJECTED,
            UserEstablishmentStatus.REVOKED,
            UserEstablishmentStatus.WITHDRAWN,
        ],
    )
    async def test_closed_relation_is_re_requested(self, status):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, status)]
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

    @pytest.mark.parametrize(
        "status",
        [UserEstablishmentStatus.APPROVED, UserEstablishmentStatus.PENDING],
    )
    async def test_open_relation_is_untouched(self, status):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, status)]
        uow = _make_uow(user=user, relations=relations, establishments_by_ids=[estab])
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab.id]
        )

        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        assert result[0].status == status

    async def test_mixed_batch_classifies_each_id(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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

    async def test_duplicate_ids_are_deduplicated(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = _make_establishment()
        uow = _make_uow(user=user, relations=[], establishments_by_ids=[estab])
        service = UserService(uow)

        result = await service.request_establishment_access(
            _actor_for(user), [estab.id, estab.id]
        )

        assert uow.user_establishment_repo.preset_relation.await_count == 1
        assert len(result) == 1

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPERADMIN])
    async def test_admin_is_rejected_and_writes_nothing(self, role):
        """An admin subscribes instead of requesting access for review."""
        user = _make_user(role=role)
        estab = _make_establishment()
        uow = _make_uow(user=user, relations=[], establishments_by_ids=[estab])
        service = UserService(uow)

        with pytest.raises(RoleNotAllowedError):
            await service.request_establishment_access(_actor_for(user), [estab.id])

        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.commit.assert_not_called()

    async def test_unknown_establishment_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
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


class TestWithdrawEstablishmentAccess:
    @pytest.mark.parametrize(
        "status",
        [UserEstablishmentStatus.APPROVED, UserEstablishmentStatus.PENDING],
    )
    async def test_open_relation_is_withdrawn(self, status):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, status)]
        uow = _make_uow(user=user, relations=relations, establishments=[estab])
        service = UserService(uow)

        result = await service.withdraw_establishment_access(
            _actor_for(user), [estab.id]
        )

        uow.user_establishment_repo.update_status_for_ids.assert_awaited_once()
        _, ids, new_status = (
            uow.user_establishment_repo.update_status_for_ids.call_args.args
        )
        assert ids == [estab.id]
        assert new_status == UserEstablishmentStatus.WITHDRAWN
        uow.commit.assert_awaited_once()
        assert result[0].id == estab.id
        assert result[0].status == UserEstablishmentStatus.WITHDRAWN

    async def test_establishment_with_no_relation_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
        uow = _make_uow(user=user, relations=[])
        service = UserService(uow)
        missing_id = uuid.uuid4()

        with pytest.raises(UserEstablishmentNotFoundError):
            await service.withdraw_establishment_access(_actor_for(user), [missing_id])

        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.parametrize(
        "status",
        [
            UserEstablishmentStatus.REJECTED,
            UserEstablishmentStatus.REVOKED,
            UserEstablishmentStatus.WITHDRAWN,
        ],
    )
    async def test_relation_in_non_withdrawable_status_raises(self, status):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = _make_establishment()
        relations = [_make_relation(estab.id, status)]
        uow = _make_uow(user=user, relations=relations)
        service = UserService(uow)

        with pytest.raises(UserEstablishmentNotWithdrawableError) as exc_info:
            await service.withdraw_establishment_access(_actor_for(user), [estab.id])

        assert exc_info.value.extensions["relation_status"] == status.value
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_not_called()

    async def test_partial_invalid_batch_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.FIELD_WORKER)
        approved = _make_establishment()
        rejected = _make_establishment()
        relations = [
            _make_relation(approved.id, UserEstablishmentStatus.APPROVED),
            _make_relation(rejected.id, UserEstablishmentStatus.REJECTED),
        ]
        uow = _make_uow(user=user, relations=relations)
        service = UserService(uow)

        with pytest.raises(UserEstablishmentNotWithdrawableError):
            await service.withdraw_establishment_access(
                _actor_for(user), [approved.id, rejected.id]
            )

        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_not_called()


class TestSubscribeToEstablishment:
    @pytest.mark.parametrize(
        "status",
        [
            None,
            UserEstablishmentStatus.PENDING,
            UserEstablishmentStatus.REJECTED,
            UserEstablishmentStatus.REVOKED,
            UserEstablishmentStatus.WITHDRAWN,
        ],
    )
    async def test_relation_is_approved_and_committed(self, status):
        """A missing or non-approved relation ends up approved, with no review."""
        user = _make_user(role=UserRole.ADMIN)
        estab = _make_establishment()
        uow = _make_uow(user=user)
        uow.establishment_repo.get_by_id_or_raise = AsyncMock(return_value=estab)
        if status is not None:
            uow.user_establishment_repo.get_relation.return_value = _make_relation(
                estab.id, status
            )
        service = UserService(uow)

        result = await service.subscribe_to_establishment(_actor_for(user), estab.id)

        uow.user_establishment_repo.create_or_approve_relation.assert_awaited_once_with(
            user.id, estab.id
        )
        uow.commit.assert_awaited_once()
        assert result.id == estab.id
        assert result.status == UserEstablishmentStatus.APPROVED

    async def test_already_approved_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.ADMIN)
        estab = _make_establishment()
        uow = _make_uow(user=user)
        uow.establishment_repo.get_by_id_or_raise = AsyncMock(return_value=estab)
        uow.user_establishment_repo.get_relation.return_value = _make_relation(
            estab.id, UserEstablishmentStatus.APPROVED
        )
        service = UserService(uow)

        with pytest.raises(EstablishmentAlreadySubscribedError):
            await service.subscribe_to_establishment(_actor_for(user), estab.id)

        uow.user_establishment_repo.create_or_approve_relation.assert_not_called()
        uow.commit.assert_not_called()

    async def test_raced_insert_raises_already_subscribed(self):
        """A concurrent subscribe that wins the insert yields a conflict."""
        user = _make_user(role=UserRole.ADMIN)
        estab = _make_establishment()
        uow = _make_uow(user=user)
        uow.establishment_repo.get_by_id_or_raise = AsyncMock(return_value=estab)
        uow.user_establishment_repo.create_or_approve_relation.side_effect = (
            UniqueConstraintError("user_establishment", (user.id, estab.id))
        )
        service = UserService(uow)

        with pytest.raises(EstablishmentAlreadySubscribedError):
            await service.subscribe_to_establishment(_actor_for(user), estab.id)

        uow.commit.assert_not_called()

    async def test_unknown_establishment_raises_and_writes_nothing(self):
        user = _make_user(role=UserRole.ADMIN)
        uow = _make_uow(user=user)
        uow.establishment_repo.get_by_id_or_raise = AsyncMock(
            side_effect=EstablishmentNotFoundError(str(uuid.uuid4()))
        )
        service = UserService(uow)

        with pytest.raises(EstablishmentNotFoundError):
            await service.subscribe_to_establishment(_actor_for(user), uuid.uuid4())

        uow.user_establishment_repo.create_or_approve_relation.assert_not_called()
        uow.commit.assert_not_called()


class TestUnsubscribeFromEstablishment:
    async def test_relation_is_deleted_and_committed(self):
        user = _make_user(role=UserRole.ADMIN)
        estab_id = uuid.uuid4()
        uow = _make_uow(user=user)
        service = UserService(uow)

        await service.unsubscribe_from_establishment(_actor_for(user), estab_id)

        uow.user_establishment_repo.delete_relation.assert_awaited_once_with(
            user.id, estab_id
        )
        uow.commit.assert_awaited_once()

    async def test_missing_relation_raises_and_commits_nothing(self):
        user = _make_user(role=UserRole.ADMIN)
        uow = _make_uow(user=user)
        uow.user_establishment_repo.delete_relation.return_value = False
        service = UserService(uow)

        with pytest.raises(UserEstablishmentNotFoundError):
            await service.unsubscribe_from_establishment(_actor_for(user), uuid.uuid4())

        uow.commit.assert_not_called()
