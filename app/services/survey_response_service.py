from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import UserEstablishmentStatus
from app.domain.pagination import PaginatedResult
from app.domain.survey import (
    QuestionDomain,
    ResponseType,
    SurveyDomain,
    SurveyInstrumentType,
    SurveyScope,
)
from app.domain.survey_response import (
    SurveyResponseDashboardItemDomain,
    SurveyResponseDetailDomain,
    SurveyResponseDomain,
)
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
# Roles allowed to fetch and see responses
_DASHBOARD_ROLES = {UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN}


class SurveyResponseService:
    """Business logic for survey response registration, retrieval and editing."""

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
        """Raise if establishment_id is outside a TARGETED survey's audience."""
        if survey.scope == SurveyScope.TARGETED and (
            establishment_id not in survey.establishment_ids
        ):
            raise InvalidSurveyResponseError(
                "Establishment is outside this survey's audience."
            )

    @staticmethod
    def _assert_owner_or_admin(actor: UserActor, response: SurveyResponse) -> None:
        """Raise unless actor is the original submitter or an admin/superadmin."""
        if actor.role in _ADMIN_ROLES:
            return
        if str(response.submitted_by_id) == str(actor.user_id):
            return
        raise ForbiddenError()

    @staticmethod
    def _validate_answers(
        questions: list[QuestionDomain], answers: dict[str, object]
    ) -> dict[str, object]:
        """Validate answers against their questions' requirements and shape;
        return them, or raise InvalidSurveyResponseError."""
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
        """Raise if value doesn't match question's response_type. TEXT and DATE
        are accepted as-is: DATE's ISO-8601 shape is already validated at the
        schema layer, before this method runs."""
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

    async def get(self, response_id: UUID, actor: UserActor) -> SurveyResponseDomain:
        """Return a response's full detail, including its answers.

        Does not re-check establishment access, so a submitter keeps read access
        to their own response even after losing access to its establishment.

        Raises:
            SurveyResponseNotFoundError.
            ForbiddenError: not the submitter and not admin/superadmin.
        """
        response = await self._get_response_or_raise(response_id)
        self._assert_owner_or_admin(actor, response)
        return SurveyResponseDomain.from_db(response)

    async def submit(
        self, data: SurveyResponseRequest, actor: UserActor
    ) -> tuple[SurveyResponseDomain, bool]:
        """Idempotently register a survey response.

        Returns (response, created): created is False when replaying an existing
        id, True for a new response. Permission checks apply even on replay,
        against the existing response's establishment.

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
        score_fies = self._calculate_fies_score(survey, answers)

        try:
            response = await self.uow.survey_response_repo.create(
                id=data.id,
                survey_id=data.survey_id,
                establishment_id=data.establishment_id,
                submitted_by_id=actor.user_id,
                answers=answers,
                score_fies=score_fies,
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
        recent as what it already has (last-write-wins).The FIES score is
        recalculated from the new answers whenever the edit is applied.

        Raises:
            SurveyResponseNotFoundError, ForbiddenError (not the submitter/admin),
            InvalidSurveyResponseError (answers fail validation).
        """
        response = await self._get_response_or_raise(response_id)
        self._assert_owner_or_admin(actor, response)

        if data.id is not None:
            existing_edit = await self.uow.survey_response_edit_repo.get_by_id(data.id)
            if existing_edit is not None:
                return SurveyResponseDomain.from_db(response)

        survey = await self._get_survey_or_raise(response.survey_id)
        answers = self._validate_answers(survey.questions, data.answers)
        score_fies = self._calculate_fies_score(survey, answers)

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
                response, answers=answers, score_fies=score_fies, event_at=data.event_at
            )
        await self.uow.commit()
        return SurveyResponseDomain.from_db(response)

    async def list_by_survey(
        self, survey_id: UUID, actor: UserActor, page: int, page_size: int
    ) -> PaginatedResult[SurveyResponseDashboardItemDomain]:
        """Return a paginated list of a survey's responses, newest event_at first.

        Raises:
            ForbiddenError: actor role isn't a dashboard reader.
            SurveyNotFoundError.
        """
        if actor.role not in _DASHBOARD_ROLES:
            raise ForbiddenError()
        await self._get_survey_or_raise(survey_id)

        page = max(1, page)
        offset = (page - 1) * page_size
        responses, total = await self.uow.survey_response_repo.list_by_survey(
            survey_id, limit=page_size, offset=offset
        )
        items = [SurveyResponseDashboardItemDomain.from_db(r) for r in responses]
        return PaginatedResult.build(
            items=items, total=total, page=page, page_size=page_size
        )

    async def get_response_detail(
        self, response_id: UUID, actor: UserActor
    ) -> SurveyResponseDetailDomain:
        """Return one user's full response detail for the dashboard: every
        question in the survey and the value that user registered for it.

        Raises:
            ForbiddenError: actor role isn't a dashboard reader.
            SurveyResponseNotFoundError.
        """
        if actor.role not in _DASHBOARD_ROLES:
            raise ForbiddenError()
        response = await self.uow.survey_response_repo.get_with_relations(response_id)
        if response is None:
            raise SurveyResponseNotFoundError(str(response_id))
        return SurveyResponseDetailDomain.from_db(response)

    @staticmethod
    def _calculate_fies_score(
        survey: SurveyDomain, answers: dict[str, object]
    ) -> int | None:
        """Return the FIES raw score (0-8): the count of affirmative answers
        among this FIES survey's questions. None if the survey isn't FIES.

        This is the raw score only. The FAO's full methodology additionally
        calibrates raw scores against a Rasch (IRT) model with globally
        published item-severity parameters, to make scores comparable across
        populations — that equating step is out of scope here; it would run
        as a periodic batch analysis over accumulated responses, not per
        submission. See: FAO, "Voices of the Hungry" FIES methodology.

        TODO: add Rasch-based equating as a separate offline/batch process
        once there's a large enough response set to calibrate against.
        """
        if survey.instrument_type != SurveyInstrumentType.FIES:
            return None
        return sum(
            1
            for question in survey.questions
            for option in question.options
            if option.position == 0 and answers.get(str(question.id)) == str(option.id)
        )
