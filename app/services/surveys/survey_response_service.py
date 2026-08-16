from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.pagination import PaginatedResult
from app.domain.survey import (
    QuestionDomain,
    ResponseType,
    SurveyDomain,
    SurveyInstrumentType,
    SurveyResponseTarget,
)
from app.domain.survey_response import (
    SurveyResponseDashboardItemDomain,
    SurveyResponseDetailDomain,
    SurveyResponseDomain,
    SurveyResponseListingParams,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    InvalidListingFilterError,
    InvalidSurveyResponseError,
    SubjectNotFoundError,
    SurveyNotFoundError,
    SurveyResponseAlreadyExistsError,
    SurveyResponseNotFoundError,
    UniqueConstraintError,
)
from app.models.subjects.subject import Subject
from app.models.surveys.survey_response import SurveyResponse
from app.schemas.surveys.survey_response_schema import (
    ExistingResponseRef,
    SurveyResponseEditRequest,
    SurveyResponseRequest,
    UserRefResponse,
)
from app.services.exporters.base import SurveyResponseExporter

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

    @staticmethod
    def _resolve_target(
        survey: SurveyDomain, data: SurveyResponseRequest
    ) -> tuple[UUID | None, UUID | None]:
        """Return ``(subject_id, establishment_id)`` for this survey's target."""
        target = survey.response_target
        if target == SurveyResponseTarget.SUBJECT:
            if data.subject_id is None or data.establishment_id is not None:
                raise InvalidSurveyResponseError(
                    "This survey requires a subject_id and no establishment_id."
                )
            return data.subject_id, None
        if target == SurveyResponseTarget.ESTABLISHMENT:
            if data.establishment_id is None or data.subject_id is not None:
                raise InvalidSurveyResponseError(
                    "This survey requires an establishment_id and no subject_id."
                )
            return None, data.establishment_id
        if data.subject_id is not None or data.establishment_id is not None:
            raise InvalidSurveyResponseError(
                "This survey is anonymous and accepts no subject_id or "
                "establishment_id."
            )
        return None, None

    @staticmethod
    def _assert_establishment_filters_applicable(
        survey: SurveyDomain,
        *,
        establishment_id: UUID | None = None,
        city: str | None = None,
        province: str | None = None,
    ) -> None:
        """Reject establishment-based filters on a survey with no establishments."""
        if survey.response_target == SurveyResponseTarget.ESTABLISHMENT:
            return
        if establishment_id is not None:
            raise InvalidListingFilterError(
                "The establishment filter only applies to surveys targeted at "
                "establishments."
            )
        if city or province:
            raise InvalidListingFilterError(
                "City and province filters only apply to surveys targeted at "
                "establishments."
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

    async def _get_response_or_raise(self, response_id: UUID) -> SurveyResponse:
        response = await self.uow.survey_response_repo.get_by_id(response_id)
        if response is None:
            raise SurveyResponseNotFoundError(str(response_id))
        return response

    async def _get_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

    @staticmethod
    def _target_conflict_error(
        existing: SurveyResponse,
    ) -> SurveyResponseAlreadyExistsError:
        """Build the 409 naming the response already recorded for a target.

        Serialized here because the RFC 7807 handler passes extensions straight
        to JSONResponse, which cannot encode a raw UUID or datetime.
        """
        return SurveyResponseAlreadyExistsError(
            ExistingResponseRef(
                id=existing.id,
                submitted_by=UserRefResponse(
                    id=existing.submitted_by.id, name=existing.submitted_by.name
                ),
                event_at=existing.event_at,
            ).model_dump(mode="json")
        )

    async def _raise_if_target_answered(
        self,
        survey_id: UUID,
        subject_id: UUID | None,
        establishment_id: UUID | None,
    ) -> None:
        """Raise the 409 if this survey's target has already answered it."""
        if subject_id is None and establishment_id is None:
            return
        existing = await self.uow.survey_response_repo.get_by_target(
            survey_id, subject_id=subject_id, establishment_id=establishment_id
        )
        if existing is not None:
            raise self._target_conflict_error(existing)

    @staticmethod
    def _replayed(existing: SurveyResponse, survey_id: UUID) -> SurveyResponseDomain:
        """Return a replayed response, rejecting an id reused across surveys."""
        if existing.survey_id != survey_id:
            raise InvalidSurveyResponseError(
                "This response id already belongs to a different survey."
            )
        return SurveyResponseDomain.from_db(existing)

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
        self, survey_id: UUID, data: SurveyResponseRequest, actor: UserActor
    ) -> tuple[SurveyResponseDomain, bool]:
        """Idempotently register a survey response.

        Returns (response, created): created is False when replaying an existing
        id, True for a new response. The id is checked before the
        one-response-per-target rule, so a retried sync never conflicts with
        itself.

        Raises:
            ForbiddenError: role can't submit.
            SurveyNotFoundError / EstablishmentNotFoundError / SubjectNotFoundError.
            InvalidSurveyResponseError: payload names an entity that does not
                match the survey's response target, answers fail validation, or
                the replayed id belongs to a different survey.
            SurveyResponseAlreadyExistsError: this subject or establishment has
                already answered this survey.
        """
        self._assert_can_submit(actor)

        if data.id is not None:
            existing = await self.uow.survey_response_repo.get_by_id(data.id)
            if existing is not None:
                return self._replayed(existing, survey_id), False

        survey = await self._get_survey_or_raise(survey_id)
        subject_id, establishment_id = self._resolve_target(survey, data)
        if establishment_id is not None:
            await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        if subject_id is not None:
            await self._get_subject_or_raise(subject_id)
        await self._raise_if_target_answered(survey_id, subject_id, establishment_id)
        answers = self._validate_answers(survey.questions, data.answers)
        score_fies = self._calculate_fies_score(survey, answers)

        try:
            response = await self.uow.survey_response_repo.create(
                id=data.id,
                survey_id=survey_id,
                subject_id=subject_id,
                establishment_id=establishment_id,
                submitted_by_id=actor.user_id,
                answers=answers,
                score_fies=score_fies,
                event_at=data.event_at,
            )
        except UniqueConstraintError as error:
            # A target collision is a real conflict; an id collision is a raced
            # replay. They take different paths.
            if error.field in {"subject_id", "establishment_id"}:
                await self._raise_if_target_answered(
                    survey_id, subject_id, establishment_id
                )
                raise InvalidSurveyResponseError(
                    "This survey has already been answered for that target."
                )
            if data.id is not None:
                raced = await self.uow.survey_response_repo.get_by_id(data.id)
                if raced is not None:
                    return self._replayed(raced, survey_id), False
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
        self,
        survey_id: UUID,
        actor: UserActor,
        page: int,
        page_size: int,
        params: SurveyResponseListingParams,
    ) -> PaginatedResult[SurveyResponseDashboardItemDomain]:
        """Return a paginated list of a survey's responses, newest event_at first.

        Raises:
            ForbiddenError: actor role isn't a dashboard reader.
            SurveyNotFoundError.
            InvalidListingFilterError: an establishment, city or province filter
                was applied to a survey whose responses carry no establishment.
        """
        if actor.role not in _DASHBOARD_ROLES:
            raise ForbiddenError()
        survey = await self._get_survey_or_raise(survey_id)
        self._assert_establishment_filters_applicable(
            survey,
            establishment_id=params.establishment_id,
            city=params.city,
            province=params.province,
        )

        page = max(1, page)
        offset = (page - 1) * page_size
        responses, total = await self.uow.survey_response_repo.list_by_survey(
            survey_id, limit=page_size, offset=offset, params=params
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

    async def export(
        self,
        survey_id: UUID,
        actor: UserActor,
        exporter: SurveyResponseExporter,
        establishment_id: UUID | None = None,
    ) -> bytes:
        """Export every response to a survey using the given exporter.

        Optionally filter by establishment.

        Raises:
            ForbiddenError: actor role isn't a dashboard reader.
            SurveyNotFoundError.
            InvalidListingFilterError: an establishment filter was applied to a
                survey whose responses carry no establishment.
        """
        if actor.role not in _DASHBOARD_ROLES:
            raise ForbiddenError()
        survey = await self._get_survey_or_raise(survey_id)
        self._assert_establishment_filters_applicable(
            survey, establishment_id=establishment_id
        )

        responses = await self.uow.survey_response_repo.list_all_for_export(
            survey_id, establishment_id
        )
        detailed = [SurveyResponseDetailDomain.from_db(r) for r in responses]
        return exporter.export(survey, detailed)
