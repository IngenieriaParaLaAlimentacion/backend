import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.survey import (
    SurveyResponseTarget,
)
from app.domain.survey_response import (
    SurveyResponseListingParams,
)
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    InvalidListingFilterError,
    SurveyNotFoundError,
)
from app.services.surveys.survey_response_service import SurveyResponseService
from tests.unit.surveys.response_service.helpers import (
    _make_survey_orm,
)


class TestExport:
    async def test_admin_can_export(self, make_uow, admin_actor):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()
        fake_exporter.export.return_value = b"fake-bytes"

        result = await SurveyResponseService(uow).export(
            survey.id,
            admin_actor,
            fake_exporter,
            SurveyResponseListingParams(establishment_id=uuid.uuid4()),
        )

        assert result == b"fake-bytes"
        fake_exporter.export.assert_called_once()

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        fake_exporter = MagicMock()

        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).export(
                survey.id,
                field_worker_actor,
                fake_exporter,
                SurveyResponseListingParams(establishment_id=uuid.uuid4()),
            )
        fake_exporter.export.assert_not_called()

    async def test_survey_not_found(self, make_uow, admin_actor):
        uow = make_uow(survey=None)
        fake_exporter = MagicMock()

        with pytest.raises(SurveyNotFoundError):
            await SurveyResponseService(uow).export(
                uuid.uuid4(),
                admin_actor,
                fake_exporter,
                SurveyResponseListingParams(establishment_id=uuid.uuid4()),
            )

    async def test_filters_by_establishment(self, make_uow, admin_actor):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        establishment_id = uuid.uuid4()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()
        fake_exporter.export.return_value = b""

        await SurveyResponseService(uow).export(
            survey.id,
            admin_actor,
            fake_exporter,
            SurveyResponseListingParams(establishment_id=establishment_id),
        )

        uow.survey_response_repo.list_all_for_export.assert_awaited_once_with(
            survey.id,
            params=SurveyResponseListingParams(establishment_id=establishment_id),
        )

    @pytest.mark.parametrize(
        "target",
        [SurveyResponseTarget.SUBJECT, SurveyResponseTarget.ANONYMOUS],
    )
    async def test_establishment_filter_rejected_without_establishments(
        self, make_uow, admin_actor, target
    ):
        survey = _make_survey_orm(response_target=target)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()

        with pytest.raises(InvalidListingFilterError):
            await SurveyResponseService(uow).export(
                survey.id,
                admin_actor,
                fake_exporter,
                SurveyResponseListingParams(establishment_id=uuid.uuid4()),
            )
        uow.survey_response_repo.list_all_for_export.assert_not_called()

    async def test_unfiltered_export_allowed_for_any_target(
        self, make_uow, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()
        fake_exporter.export.return_value = b""

        await SurveyResponseService(uow).export(
            survey.id, admin_actor, fake_exporter, SurveyResponseListingParams()
        )

        uow.survey_response_repo.list_all_for_export.assert_awaited_once_with(
            survey.id, params=SurveyResponseListingParams()
        )

    async def test_filters_by_subject(self, make_uow, admin_actor):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        subject_id = uuid.uuid4()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()
        fake_exporter.export.return_value = b""

        await SurveyResponseService(uow).export(
            survey.id,
            admin_actor,
            fake_exporter,
            SurveyResponseListingParams(subject_id=subject_id),
        )

        uow.survey_response_repo.list_all_for_export.assert_awaited_once_with(
            survey.id, params=SurveyResponseListingParams(subject_id=subject_id)
        )

    @pytest.mark.parametrize(
        "target",
        [SurveyResponseTarget.ESTABLISHMENT, SurveyResponseTarget.ANONYMOUS],
    )
    async def test_subject_filter_rejected_without_subjects(
        self, make_uow, admin_actor, target
    ):
        survey = _make_survey_orm(response_target=target)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()

        with pytest.raises(InvalidListingFilterError):
            await SurveyResponseService(uow).export(
                survey.id,
                admin_actor,
                fake_exporter,
                SurveyResponseListingParams(subject_id=uuid.uuid4()),
            )
        uow.survey_response_repo.list_all_for_export.assert_not_called()
