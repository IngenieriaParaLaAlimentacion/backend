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
    FilterNotApplicableError,
    InvalidSurveyResponseError,
    NotResourceOwnerError,
    RoleNotAllowedError,
    SubjectNotFoundError,
    SurveyNotFoundError,
    SurveyResponseAlreadyExistsError,
    SurveyResponseNotFoundError,
    UniqueConstraintError,
)
from app.models.subjects.subject import Subject
from app.models.surveys.survey_response import SurveyResponse
from app.models.surveys.survey_response_edit import SurveyResponseEdit
from app.schemas.surveys.survey_response_schema import (
    ExistingResponseRef,
    SurveyResponseEditRequest,
    SurveyResponseRequest,
    UserRefResponse,
)
from app.services.access import check_field_work_access
from app.services.exporters.base import SurveyResponseExporter

# Roles allowed to submit a response. Analysts are further scoped by
# check_field_work_access.
_SUBMITTER_ROLES = {
    UserRole.FIELD_WORKER,
    UserRole.ANALYST,
    UserRole.ADMIN,
    UserRole.SUPERADMIN,
}
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
            raise RoleNotAllowedError("Your role cannot submit survey responses.")

    @staticmethod
    def _assert_dashboard_reader(actor: UserActor) -> None:
        if actor.role not in _DASHBOARD_ROLES:
            raise RoleNotAllowedError("Your role cannot read the survey dashboard.")

    @staticmethod
    def _resolve_target(
        survey: SurveyDomain, data: SurveyResponseRequest
    ) -> tuple[UUID | None, UUID | None]:
        """Return ``(subject_id, establishment_id)`` for this survey's target."""
        target = survey.response_target
        if target == SurveyResponseTarget.SUBJECT:
            if data.subject_id is None or data.establishment_id is not None:
                raise InvalidSurveyResponseError(
                    "This survey requires a subject_id and no establishment_id.",
                )
            return data.subject_id, None
        if target == SurveyResponseTarget.ESTABLISHMENT:
            if data.establishment_id is None or data.subject_id is not None:
                raise InvalidSurveyResponseError(
                    "This survey requires an establishment_id and no subject_id.",
                )
            return None, data.establishment_id
        if data.subject_id is not None or data.establishment_id is not None:
            raise InvalidSurveyResponseError(
                "This survey is anonymous and accepts no subject_id or "
                "establishment_id.",
            )
        return None, None

    @staticmethod
    def _validate_response_number(
        survey: SurveyDomain,
        response_number: int | None,
    ) -> int | None:
        """Enforce the survey's conditional response-number invariant."""
        if survey.requires_response_number is True and response_number is None:
            raise InvalidSurveyResponseError("This survey requires a response_number.")
        return response_number

    @staticmethod
    def _assert_target_filters_applicable(
        survey: SurveyDomain,
        *,
        subject_id: UUID | None = None,
        establishment_id: UUID | None = None,
        city: str | None = None,
        province: str | None = None,
    ) -> None:
        """Reject filters that resolve through a target this survey's responses
        do not carry."""
        targets_subject = survey.response_target == SurveyResponseTarget.SUBJECT
        targets_establishment = (
            survey.response_target == SurveyResponseTarget.ESTABLISHMENT
        )

        if subject_id is not None and not targets_subject:
            raise FilterNotApplicableError(
                "The subject filter only applies to surveys targeted at subjects."
            )
        if establishment_id is not None and not targets_establishment:
            raise FilterNotApplicableError(
                "The establishment filter only applies to surveys targeted at "
                "establishments."
            )
        if (city or province) and not targets_establishment:
            raise FilterNotApplicableError(
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
        raise NotResourceOwnerError(
            "Only the field worker who submitted this response, or an admin, "
            "can modify it."
        )

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
                    f"Invalid option for question '{question.text}'.",
                )
        elif question.response_type == ResponseType.MULTIPLE_CHOICE:
            if not isinstance(value, list) or not set(value) <= option_ids:
                raise InvalidSurveyResponseError(
                    f"Invalid options for question '{question.text}'.",
                )
        elif question.response_type == ResponseType.NUMERIC:
            if not isinstance(value, (int, float)):
                raise InvalidSurveyResponseError(
                    f"Question '{question.text}' expects a number.",
                )

    async def _get_survey_or_raise(self, survey_id: UUID) -> SurveyDomain:
        survey = await self.uow.survey_repo.get_by_id(survey_id)
        if survey is None:
            raise SurveyNotFoundError(str(survey_id))
        return SurveyDomain.from_db(survey)

    async def _get_response_or_raise(
        self, survey_id: UUID, response_id: UUID
    ) -> SurveyResponse:
        response = await self.uow.survey_response_repo.get_by_id(response_id)
        # A response of another survey is reported as missing, so the URL of one
        # survey never confirms that an id exists in a different one.
        if response is None or response.survey_id != survey_id:
            raise SurveyResponseNotFoundError(str(response_id))
        return response

    async def _get_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

    @staticmethod
    def _conflict_error(
        existing: SurveyResponse | None,
    ) -> SurveyResponseAlreadyExistsError:
        """Build the 409 naming what already holds the response target.

        Serialized here because the RFC 7807 handler passes extensions straight
        to JSONResponse, which cannot encode a raw UUID or datetime.
        """
        ref = (
            ExistingResponseRef(
                id=existing.id,
                submitted_by=UserRefResponse(
                    id=existing.submitted_by.id,
                    name=existing.submitted_by.name,
                    last_name=existing.submitted_by.last_name,
                ),
                event_at=existing.event_at,
                response_number=existing.response_number,
            ).model_dump(mode="json")
            if existing is not None
            else None
        )
        return SurveyResponseAlreadyExistsError(existing=ref)

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
            raise self._conflict_error(existing)

    @staticmethod
    def _replayed(existing: SurveyResponse, survey_id: UUID) -> SurveyResponseDomain:
        """Return a replayed response, rejecting an id reused across surveys."""
        if existing.survey_id != survey_id:
            raise InvalidSurveyResponseError(
                "This response id already belongs to a different survey.",
            )
        return SurveyResponseDomain.from_db(existing)

    @staticmethod
    def _replayed_edit(
        existing_edit: SurveyResponseEdit, response: SurveyResponse
    ) -> SurveyResponseDomain:
        """Return a replayed edit's response, rejecting an id of another response."""
        if existing_edit.response_id != response.id:
            raise InvalidSurveyResponseError(
                "This edit id already belongs to a different response.",
            )
        return SurveyResponseDomain.from_db(response)

    async def get(
        self, survey_id: UUID, response_id: UUID, actor: UserActor
    ) -> SurveyResponseDomain:
        """Return a response of the given survey, including its answers.

        Does not re-check establishment access, so a submitter keeps read access
        to their own response even after losing access to its establishment.

        Raises:
            SurveyResponseNotFoundError.
            NotResourceOwnerError: not the submitter and not admin/superadmin.
        """
        response = await self._get_response_or_raise(survey_id, response_id)
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
            RoleNotAllowedError: role can't submit.
            EstablishmentAccessDeniedError: analyst without approved access to
                the response's establishment, or to any establishment when the
                response names none.
            SurveyNotFoundError / EstablishmentNotFoundError / SubjectNotFoundError.
            InvalidSurveyResponseError: payload names an entity that does not
                match the survey's response target, answers fail validation, or
                the replayed id belongs to a different survey.
            SurveyResponseAlreadyExistsError: target conflict.
        """
        self._assert_can_submit(actor)

        if data.id is not None:
            existing = await self.uow.survey_response_repo.get_by_id(data.id)
            if existing is not None:
                await check_field_work_access(
                    self.uow, actor, existing.establishment_id
                )
                return self._replayed(existing, survey_id), False

        survey = await self._get_survey_or_raise(survey_id)
        subject_id, establishment_id = self._resolve_target(survey, data)
        if establishment_id is not None:
            await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_field_work_access(self.uow, actor, establishment_id)
        if subject_id is not None:
            await self._get_subject_or_raise(subject_id)
        await self._raise_if_target_answered(survey_id, subject_id, establishment_id)
        response_number = self._validate_response_number(survey, data.response_number)
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
                response_number=response_number,
                event_at=data.event_at,
            )
        except UniqueConstraintError as error:
            # A target collision is a real conflict; an id collision is a raced
            # replay. They take different paths.
            if error.field in {"subject_id", "establishment_id"}:
                await self._raise_if_target_answered(
                    survey_id, subject_id, establishment_id
                )
                # The conflicting row lost the read race, so it cannot be named
                # here -- but the condition is the same one the pre-check above
                # reports, and must not leave with a different contract.
                raise self._conflict_error(None)
            if data.id is not None:
                raced = await self.uow.survey_response_repo.get_by_id(data.id)
                if raced is not None:
                    return self._replayed(raced, survey_id), False
            raise

        await self.uow.survey_repo.increment_response_count(survey.id)
        await self.uow.commit()
        return SurveyResponseDomain.from_db(response), True

    async def edit(
        self,
        survey_id: UUID,
        response_id: UUID,
        data: SurveyResponseEditRequest,
        actor: UserActor,
    ) -> SurveyResponseDomain:
        """Full-replace edit of a response's answers and response number.

        Every edit attempt appends a row to ``survey_response_edits``; the
        response's current state only advances if ``event_at`` is at least as
        recent as what it already has (last-write-wins). The FIES score is
        recalculated from the new answers whenever the edit is applied.

        Raises:
            SurveyResponseNotFoundError, NotResourceOwnerError (not the
            submitter/admin), EstablishmentAccessDeniedError (analyst without
            the approved access that submitting requires),
            InvalidSurveyResponseError (answers fail validation).
        """
        response = await self._get_response_or_raise(survey_id, response_id)
        self._assert_owner_or_admin(actor, response)
        await check_field_work_access(self.uow, actor, response.establishment_id)

        if data.id is not None:
            existing_edit = await self.uow.survey_response_edit_repo.get_by_id(data.id)
            if existing_edit is not None:
                return self._replayed_edit(existing_edit, response)

        survey = await self._get_survey_or_raise(response.survey_id)
        response_number = self._validate_response_number(survey, data.response_number)
        answers = self._validate_answers(survey.questions, data.answers)
        score_fies = self._calculate_fies_score(survey, answers)

        try:
            await self.uow.survey_response_edit_repo.create(
                id=data.id,
                response_id=response.id,
                edited_by_id=actor.user_id,
                answers=answers,
                response_number=response_number,
                event_at=data.event_at,
            )
        except UniqueConstraintError:
            if data.id is not None:
                raced = await self.uow.survey_response_edit_repo.get_by_id(data.id)
                if raced is not None:
                    return self._replayed_edit(raced, response)
            raise

        if data.event_at >= response.event_at:
            response = await self.uow.survey_response_repo.update_answers(
                response,
                answers=answers,
                score_fies=score_fies,
                response_number=response_number,
                event_at=data.event_at,
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
        """Return a paginated list of a survey's responses in ``params.sort_order``.

        ``params`` may narrow by response number, exactly or by range.

        Raises:
            RoleNotAllowedError: actor role isn't a dashboard reader.
            SurveyNotFoundError.
            FilterNotApplicableError: a filter was applied to a survey whose
                responses carry no such target — a subject filter on a survey
                not targeted at subjects, or an establishment/city/province one
                on a survey not targeted at establishments.
        """
        self._assert_dashboard_reader(actor)
        survey = await self._get_survey_or_raise(survey_id)
        self._assert_target_filters_applicable(
            survey,
            subject_id=params.subject_id,
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
        self, survey_id: UUID, response_id: UUID, actor: UserActor
    ) -> SurveyResponseDetailDomain:
        """Return one user's full response detail for the dashboard: every
        question in the survey and the value that user registered for it.

        Raises:
            RoleNotAllowedError: actor role isn't a dashboard reader.
            SurveyResponseNotFoundError.
        """
        self._assert_dashboard_reader(actor)
        response = await self.uow.survey_response_repo.get_with_relations(response_id)
        if response is None or response.survey_id != survey_id:
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
        params: SurveyResponseListingParams,
    ) -> bytes:
        """Export responses using the listing's filters.

        Raises:
            RoleNotAllowedError: actor role isn't a dashboard reader.
            SurveyNotFoundError.
            FilterNotApplicableError: a target filter was applied to a survey
                whose responses do not carry that target.
        """
        self._assert_dashboard_reader(actor)
        survey = await self._get_survey_or_raise(survey_id)
        self._assert_target_filters_applicable(
            survey,
            subject_id=params.subject_id,
            establishment_id=params.establishment_id,
            city=params.city,
            province=params.province,
        )

        responses = await self.uow.survey_response_repo.list_all_for_export(
            survey_id, params=params
        )
        detailed = [SurveyResponseDetailDomain.from_db(r) for r in responses]
        return exporter.export(survey, detailed)
