import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.user import UserActor, UserRole
from tests.unit.surveys.response_service.helpers import (
    _UNSET,
    _apply_update_answers,
    _make_response,
)


@pytest.fixture
def make_uow(stub_establishment_lookup):
    def _make(
        survey=None,
        establishment=_UNSET,
        relation=None,
        existing_response=None,
        created_response=None,
        existing_edit=None,
        subject=_UNSET,
        target_response=None,
    ):
        uow = AsyncMock()
        uow.survey_repo.get_by_id = AsyncMock(return_value=survey)
        stub_establishment_lookup(
            uow, MagicMock() if establishment is _UNSET else establishment
        )
        uow.subject_repo.get_by_id = AsyncMock(
            return_value=MagicMock() if subject is _UNSET else subject
        )
        uow.user_establishment_repo.get_relation = AsyncMock(return_value=relation)
        uow.survey_response_repo.get_by_target = AsyncMock(return_value=target_response)
        uow.survey_response_repo.get_by_id = AsyncMock(return_value=existing_response)
        uow.survey_response_repo.create = AsyncMock(
            return_value=created_response or _make_response()
        )
        uow.survey_response_repo.update_answers = AsyncMock(
            side_effect=_apply_update_answers
        )
        uow.survey_response_edit_repo.get_by_id = AsyncMock(return_value=existing_edit)
        uow.survey_response_edit_repo.create = AsyncMock()
        uow.survey_repo.increment_response_count = AsyncMock()
        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def admin_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


@pytest.fixture
def analyst_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ANALYST)


@pytest.fixture
def field_worker_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)
