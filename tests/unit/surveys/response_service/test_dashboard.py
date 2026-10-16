import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.survey import (
    ResponseType,
    SurveyInstrumentType,
)
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    SurveyResponseNotFoundError,
)
from app.services.surveys.survey_response_service import SurveyResponseService
from tests.unit.surveys.response_service.helpers import (
    NOW,
    _make_option,
    _make_question,
    _make_response,
    _make_survey_orm,
)


def _make_fies_survey_orm(num_questions: int = 8) -> tuple[MagicMock, list[MagicMock]]:
    """A FIES-marked survey ORM double with `num_questions` dichotomous
    single_choice questions: option[0]="Sí" (affirmative, position 0),
    option[1]="No" (position 1)."""
    questions = []
    for i in range(num_questions):
        yes = _make_option("Sí")
        yes.position = 0
        no = _make_option("No")
        no.position = 1
        q = _make_question(
            response_type=ResponseType.SINGLE_CHOICE,
            is_required=True,
            options=[yes, no],
        )
        q.position = i
        questions.append(q)
    survey = _make_survey_orm(questions=questions)
    survey.instrument_type = SurveyInstrumentType.FIES
    return survey, questions


def _make_response_with_detail(
    questions: list,
    answers: dict,
    submitted_by_id: uuid.UUID | None = None,
    submitted_by_name: str = "Juana",
    submitted_by_last_name: str = "Pérez",
) -> MagicMock:
    survey = MagicMock()
    survey.id = uuid.uuid4()
    survey.name = "Encuesta FIES"
    survey.questions = questions

    establishment = MagicMock()
    establishment.id = uuid.uuid4()

    submitter = MagicMock()
    submitter.id = submitted_by_id or uuid.uuid4()
    submitter.name = submitted_by_name
    submitter.last_name = submitted_by_last_name

    r = MagicMock()
    r.id = uuid.uuid4()
    r.event_at = NOW
    r.answers = answers
    r.survey = survey
    r.survey_id = survey.id
    r.establishment = establishment
    r.submitted_by = submitter
    return r


class TestGetDashboardDetail:
    async def test_admin_gets_full_detail_with_resolved_labels(
        self, make_uow, admin_actor
    ):
        option_yes = _make_option("Sí")
        option_no = _make_option("No")
        choice_question = _make_question(
            response_type=ResponseType.SINGLE_CHOICE, options=[option_yes, option_no]
        )
        choice_question.position = 0
        text_question = _make_question(response_type=ResponseType.TEXT)
        text_question.position = 1

        response = _make_response_with_detail(
            questions=[text_question, choice_question],
            answers={
                str(choice_question.id): str(option_yes.id),
                str(text_question.id): "Todo bien",
            },
        )
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.survey_id, response.id, admin_actor
        )

        assert [a.question_id for a in result.answers] == [
            choice_question.id,
            text_question.id,
        ]
        choice_answer, text_answer = result.answers
        assert text_answer.value == "Todo bien"
        assert text_answer.value_label is None
        assert choice_answer.value_label == "Sí"
        assert result.submitted_by.name == "Juana"
        assert result.submitted_by.last_name == "Pérez"

    async def test_multiple_choice_resolves_all_labels(self, make_uow, admin_actor):
        option_a = _make_option("Verduras")
        option_b = _make_option("Frutas")
        question = _make_question(
            response_type=ResponseType.MULTIPLE_CHOICE, options=[option_a, option_b]
        )
        response = _make_response_with_detail(
            questions=[question],
            answers={str(question.id): [str(option_a.id), str(option_b.id)]},
        )
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.survey_id, response.id, admin_actor
        )

        assert result.answers[0].value_label == ["Verduras", "Frutas"]

    async def test_unanswered_question_has_none_value_and_label(
        self, make_uow, admin_actor
    ):
        question = _make_question(response_type=ResponseType.TEXT, is_required=False)
        response = _make_response_with_detail(questions=[question], answers={})
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.survey_id, response.id, admin_actor
        )

        assert result.answers[0].value is None
        assert result.answers[0].value_label is None

    async def test_analyst_can_view(self, make_uow, analyst_actor):
        question = _make_question(response_type=ResponseType.TEXT)
        response = _make_response_with_detail(questions=[question], answers={})
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.survey_id, response.id, analyst_actor
        )
        assert result.id == response.id

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock()

        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).get_response_detail(
                uuid.uuid4(), uuid.uuid4(), field_worker_actor
            )
        uow.survey_response_repo.get_with_relations.assert_not_awaited()

    async def test_response_not_found(self, make_uow, admin_actor):
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=None)

        with pytest.raises(SurveyResponseNotFoundError):
            await SurveyResponseService(uow).get_response_detail(
                uuid.uuid4(), uuid.uuid4(), admin_actor
            )


class TestFiesScoring:
    @pytest.mark.parametrize("affirmative", [8, 0, 3])
    async def test_score_counts_the_affirmative_answers(
        self, make_uow, request_factory, admin_actor, affirmative
    ):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        answers = {
            str(q.id): str(q.options[0 if i < affirmative else 1].id)
            for i, q in enumerate(questions)
        }
        uow = make_uow(survey=survey)

        await SurveyResponseService(uow).submit(
            survey.id, request_factory(answers=answers), admin_actor
        )

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] == affirmative

    async def test_custom_survey_has_null_score(
        self, make_uow, request_factory, admin_actor
    ):
        question = _make_question(is_required=False)
        survey = _make_survey_orm(questions=[question])
        survey.instrument_type = SurveyInstrumentType.CUSTOM
        uow = make_uow(survey=survey)
        data = request_factory(answers={})

        await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] is None

    async def test_unanswered_fies_question_not_counted(
        self, make_uow, request_factory, admin_actor
    ):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        questions[0].is_required = False  # allow leaving it unanswered
        answers = {
            str(q.id): str(q.options[0].id) for q in questions[1:]
        }  # first question left unanswered, rest all "Sí"
        uow = make_uow(survey=survey)
        data = request_factory(answers=answers)

        await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] == 7

    async def test_edit_recalculates_score(self, make_uow, edit_factory, admin_actor):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        original_answers = {
            str(q.id): str(q.options[1].id) for q in questions
        }  # all "No"
        response = _make_response(survey_id=survey.id, answers=original_answers)
        uow = make_uow(survey=survey, existing_response=response)

        new_answers = {str(q.id): str(q.options[0].id) for q in questions}  # all "Sí"
        await SurveyResponseService(uow).edit(
            response.survey_id,
            response.id,
            edit_factory(answers=new_answers, event_at=NOW),
            admin_actor,
        )

        update_call = uow.survey_response_repo.update_answers.call_args
        assert update_call.kwargs["score_fies"] == 8
