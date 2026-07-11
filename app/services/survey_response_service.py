from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import UserEstablishmentStatus
from app.domain.survey import QuestionDomain, ResponseType, SurveyDomain, SurveyScope
from app.domain.survey_response import SurveyResponseDomain
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    InvalidSurveyResponseError,
    SurveyNotFoundError,
    SurveyResponseNotFoundError,
    UniqueConstraintError,
)
from app.models.survey_response import SurveyResponse
from app.schemas.survey_response_schema import (
    SurveyResponseEditRequest,
    SurveyResponseRequest,
)

# Roles allowed to submit a response.
_SUBMITTER_ROLES = {UserRole.FIELD_WORKER, UserRole.ADMIN, UserRole.SUPERADMIN}
# Roles allowed to edit any response regardless of authorship.
_ADMIN_ROLES = {UserRole.ADMIN, UserRole.SUPERADMIN}


class SurveyResponseService:
    """Business logic for survey response registration and editing (Module 2)."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    @staticmethod
    def _assert_can_submit(actor: UserActor) -> None:
        if actor.role not in _SUBMITTER_ROLES:
            raise ForbiddenError()

    async def _check_establishment_access(
        self, actor: UserActor, establishment_id: UUID
    ) -> None:
        if actor.role != UserRole.FIELD_WORKER:
            return
        relation = await self.uow.user_establishment_repo.get_relation(
            actor.user_id, establishment_id
        )
        if relation is None or relation.status != UserEstablishmentStatus.APPROVED:
            raise ForbiddenError()

    @staticmethod
    def _assert_establishment_in_survey_scope(
        survey: SurveyDomain, establishment_id: UUID
    ) -> None:
        """Applies to every role, including admins: a TARGETED survey's audience
        is a data-integrity boundary, not just a permission boundary."""
        if survey.scope == SurveyScope.TARGETED and (
            establishment_id not in survey.establishment_ids
        ):
            raise InvalidSurveyResponseError(
                "Establishment is outside this survey's audience."
            )

    @staticmethod
    def _assert_can_edit(actor: UserActor, response: SurveyResponse) -> None:
        if actor.role in _ADMIN_ROLES:
            return
        if str(response.submitted_by_id) == str(actor.user_id):
            return
        raise ForbiddenError()

    @staticmethod
    def _validate_answers(
        questions: list[QuestionDomain], answers: dict[str, object]
    ) -> dict[str, object]:
        """Enforce CA3: every required question must be answered; every provided
        answer must match its question's response_type/options. No draft mode —
        this either returns a fully valid answer set or raises."""
        question_by_id = {str(q.id): q for q in questions}
        for key in answers:
            if key not in question_by_id:
                raise InvalidSurveyResponseError(f"Unknown question id '{key}'.")
        for question in questions:
            value = answers.get(str(question.id))
            if question.is_required and (value is None or value == ""):
                raise InvalidSurveyResponseError(
                    f"Question '{question.text}' is required."
                )
            if value is not None:
                SurveyResponseService._validate_answer_shape(question, value)
        return answers

    @staticmethod
    def _validate_answer_shape(question: QuestionDomain, value: object) -> None:
        option_ids = {str(o.id) for o in question.options}
        if question.response_type == ResponseType.SINGLE_CHOICE:
            if not isinstance(value, str) or value not in option_ids:
                raise InvalidSurveyResponseError(
                    f"Invalid option for question '{question.text}'."
                )
        elif question.response_type == ResponseType.MULTIPLE_CHOICE:
            if not isinstance(value, list) or not set(value) <= option_ids:
                raise InvalidSurveyResponseError(
                    f"Invalid options for question '{question.text}'."
                )
        elif question.response_type == ResponseType.NUMERIC:
            if not isinstance(value, (int, float)):
                raise InvalidSurveyResponseError(
                    f"Question '{question.text}' expects a number."
                )
        # TEXT/DATE: accepted as opaque strings; Pydantic validates DATE's
        # ISO-8601 shape at the schema layer before this method ever runs.

    async def _get_survey_or_raise(self, survey_id: UUID) -> SurveyDomain:
        survey = await self.uow.survey_repo.get_by_id(survey_id)
        if survey is None:
            raise SurveyNotFoundError(str(survey_id))
        return SurveyDomain.from_db(survey)

    async def _get_establishment_or_raise(self, establishment_id: UUID) -> None:
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))

    async def _get_response_or_raise(self, response_id: UUID) -> SurveyResponse:
        response = await self.uow.survey_response_repo.get_by_id(response_id)
        if response is None:
            raise SurveyResponseNotFoundError(str(response_id))
        return response

    async def submit(
        self, data: SurveyResponseRequest, actor: UserActor
    ) -> tuple[SurveyResponseDomain, bool]:
        """Idempotently register a survey response.

        Returns (response, created): created=False for a replayed id (200),
        True for a brand-new response (201). Permission checks apply even on
        replay, against the existing response's establishment.

        Raises:
            ForbiddenError: role can't submit, or lacks establishment access.
            SurveyNotFoundError / EstablishmentNotFoundError.
            InvalidSurveyResponseError: establishment outside survey audience,
                or answers fail validation.
        """
        self._assert_can_submit(actor)

        if data.id is not None:
            existing = await self.uow.survey_response_repo.get_by_id(data.id)
            if existing is not None:
                await self._check_establishment_access(actor, existing.establishment_id)
                return SurveyResponseDomain.from_db(existing), False

        survey = await self._get_survey_or_raise(data.survey_id)
        await self._get_establishment_or_raise(data.establishment_id)
        await self._check_establishment_access(actor, data.establishment_id)
        self._assert_establishment_in_survey_scope(survey, data.establishment_id)
        answers = self._validate_answers(survey.questions, data.answers)

        try:
            response = await self.uow.survey_response_repo.create(
                id=data.id,
                survey_id=data.survey_id,
                establishment_id=data.establishment_id,
                submitted_by_id=actor.user_id,
                answers=answers,
                event_at=data.event_at,
            )
        except UniqueConstraintError:
            if data.id is not None:
                raced = await self.uow.survey_response_repo.get_by_id(data.id)
                if raced is not None:
                    return SurveyResponseDomain.from_db(raced), False
            raise

        await self.uow.survey_repo.increment_response_count(survey.id)
        await self.uow.commit()
        return SurveyResponseDomain.from_db(response), True

    async def edit(
        self, response_id: UUID, data: SurveyResponseEditRequest, actor: UserActor
    ) -> SurveyResponseDomain:
        """Full-replace edit of a response's answers.

        Every edit attempt appends a row to ``survey_response_edits``; the
        response's current state only advances if ``event_at`` is at least as
        recent as what it already has (last-write-wins, ADR-0004).

        Raises:
            SurveyResponseNotFoundError, ForbiddenError (not the submitter/admin),
            InvalidSurveyResponseError (answers fail validation).
        """
        response = await self._get_response_or_raise(response_id)
        self._assert_can_edit(actor, response)

        if data.id is not None:
            existing_edit = await self.uow.survey_response_edit_repo.get_by_id(data.id)
            if existing_edit is not None:
                return SurveyResponseDomain.from_db(response)

        survey = await self._get_survey_or_raise(response.survey_id)
        answers = self._validate_answers(survey.questions, data.answers)

        try:
            await self.uow.survey_response_edit_repo.create(
                id=data.id,
                response_id=response.id,
                edited_by_id=actor.user_id,
                answers=answers,
                event_at=data.event_at,
            )
        except UniqueConstraintError:
            if data.id is not None:
                raced = await self.uow.survey_response_edit_repo.get_by_id(data.id)
                if raced is not None:
                    return SurveyResponseDomain.from_db(response)
            raise

        if data.event_at >= response.event_at:
            response = await self.uow.survey_response_repo.update_answers(
                response, answers=answers, event_at=data.event_at
            )
        await self.uow.commit()
        return SurveyResponseDomain.from_db(response)
