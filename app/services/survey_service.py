from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import UserEstablishmentStatus
from app.domain.pagination import PaginatedResult
from app.domain.survey import (
    CHOICE_TYPES,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    MIN_OPTIONS,
    MIN_QUESTIONS,
    OptionInputData,
    QuestionInputData,
    SurveyDomain,
    SurveyListingParams,
    SurveyListItemDomain,
    SurveyScope,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    InvalidSurveyStructureError,
    SurveyAlreadyExistsError,
    SurveyLockedError,
    SurveyNotFoundError,
    UniqueConstraintError,
)
from app.models.survey import Survey
from app.schemas.survey_schema import (
    QuestionInput,
    SurveyCreateRequest,
    SurveyUpdateRequest,
)

# Roles allowed to author (create/duplicate) surveys.
_AUTHOR_ROLES = {UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN}
# Roles allowed to edit/delete any survey regardless of ownership.
_ADMIN_ROLES = {UserRole.ADMIN, UserRole.SUPERADMIN}


class SurveyService:
    """Business logic for backoffice survey authoring (Module 2)."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    @staticmethod
    def _assert_can_create(actor: UserActor) -> None:
        if actor.role not in _AUTHOR_ROLES:
            raise ForbiddenError()

    @staticmethod
    def _assert_can_edit(actor: UserActor, survey: Survey) -> None:
        """Allow admins/superadmins, or the analyst who authored the survey."""
        if actor.role in _ADMIN_ROLES:
            return
        if str(survey.created_by_id) == str(actor.user_id):
            return
        raise ForbiddenError()

    async def _assert_editable(
        self, survey: Survey, new_questions: list[QuestionInputData]
    ) -> None:
        """Once a survey has responses, block structural edits that would
        invalidate existing answers; allow safe ones.

        Blocked: deleting a question, changing a question's response_type,
        flipping optional -> required, or removing a choice option that some
        response already selected.
        Allowed: renaming, reordering, adding a new optional question, and
        removing a choice option nobody has selected yet.
        """
        if survey.response_count == 0:
            return
        new_by_id = {q.id: q for q in new_questions if q.id is not None}
        for question in survey.questions:
            new = new_by_id.get(question.id)
            if new is None:
                raise SurveyLockedError()
            if new.response_type != question.response_type:
                raise SurveyLockedError()
            if new.is_required and not question.is_required:
                raise SurveyLockedError()
            new_option_ids = {o.id for o in new.options if o.id is not None}
            for option in question.options:
                if option.id in new_option_ids:
                    continue
                if await self.uow.survey_response_repo.is_option_referenced(
                    survey.id, question.id, option.id
                ):
                    raise SurveyLockedError()

    async def _validate_structure(
        self,
        questions: list[QuestionInput],
        scope: SurveyScope,
        establishment_ids: list[UUID],
    ) -> None:
        if not MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS:
            raise InvalidSurveyStructureError(
                f"A survey must have between {MIN_QUESTIONS} and {MAX_QUESTIONS} "
                "questions."
            )
        for index, question in enumerate(questions):
            self._validate_question(question, index)
        self._validate_scope(scope, establishment_ids)
        if scope == SurveyScope.TARGETED:
            await self.uow.establishment_repo.get_all_by_ids(establishment_ids)

    def _validate_question(self, question: QuestionInput, index: int) -> None:
        is_choice = question.response_type in CHOICE_TYPES
        option_count = len(question.options)
        if is_choice:
            if not MIN_OPTIONS <= option_count <= MAX_OPTIONS:
                raise InvalidSurveyStructureError(
                    f"Choice question {index + 1} must have between {MIN_OPTIONS} and "
                    f"{MAX_OPTIONS} options."
                )
            self._assert_unique_options(question.options, index)
        elif option_count > 0:
            raise InvalidSurveyStructureError(
                f"Question {index + 1} of type '{question.response_type.value}' must "
                "not have options."
            )

    @staticmethod
    def _assert_unique_options(options, index: int) -> None:
        seen: set[str] = set()
        for option in options:
            key = option.text.strip().lower()
            if key in seen:
                raise InvalidSurveyStructureError(
                    f"Question {index + 1} has duplicate option '{option.text}'."
                )
            seen.add(key)

    @staticmethod
    def _validate_scope(scope: SurveyScope, establishment_ids: list[UUID]) -> None:
        if scope == SurveyScope.TARGETED and not establishment_ids:
            raise InvalidSurveyStructureError(
                "A targeted survey must reference at least one establishment."
            )
        if scope == SurveyScope.GENERIC and establishment_ids:
            raise InvalidSurveyStructureError(
                "A generic survey must not reference establishments."
            )

    @staticmethod
    def _to_question_inputs(
        questions: list[QuestionInput],
    ) -> list[QuestionInputData]:
        return [
            QuestionInputData(
                id=q.id,
                text=q.text,
                response_type=q.response_type,
                is_required=q.is_required,
                options=[OptionInputData(id=o.id, text=o.text) for o in q.options],
            )
            for q in questions
        ]

    async def _get_or_raise(self, survey_id: UUID) -> Survey:
        survey = await self.uow.survey_repo.get_by_id(survey_id)
        if survey is None:
            raise SurveyNotFoundError(str(survey_id))
        return survey

    async def _unique_copy_name(self, base_name: str) -> str:
        """Return the first free ``"<name> (copy[ N])"`` variant."""
        candidate = f"{base_name} (copy)"
        if not await self.uow.survey_repo.name_exists(candidate):
            return candidate
        suffix = 2
        while True:
            candidate = f"{base_name} (copy {suffix})"
            if not await self.uow.survey_repo.name_exists(candidate):
                return candidate
            suffix += 1

    @staticmethod
    def _build_survey_list_result(
        rows: list[tuple[Survey, int]], total: int, page: int, page_size: int
    ) -> PaginatedResult[SurveyListItemDomain]:
        return PaginatedResult.build(
            items=[
                SurveyListItemDomain.from_db(s, question_count)
                for s, question_count in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def create(self, data: SurveyCreateRequest, actor: UserActor) -> SurveyDomain:
        """Create a survey.

        Raises:
            ForbiddenError: actor role cannot author surveys.
            SurveyAlreadyExistsError: the name is already taken.
            InvalidSurveyStructureError: questions/options/scope are inconsistent.
            EstablishmentNotFoundError: a targeted establishment does not exist.
        """
        self._assert_can_create(actor)
        if await self.uow.survey_repo.name_exists(data.name):
            raise SurveyAlreadyExistsError(data.name)
        await self._validate_structure(
            data.questions, data.scope, data.establishment_ids
        )
        try:
            survey = await self.uow.survey_repo.create(
                name=data.name,
                description=data.description,
                scope=data.scope,
                created_by_id=actor.user_id,
                questions=self._to_question_inputs(data.questions),
                establishment_ids=data.establishment_ids,
            )
        except UniqueConstraintError:
            raise SurveyAlreadyExistsError(data.name)
        await self.uow.commit()
        return SurveyDomain.from_db(survey)

    async def get(self, survey_id: UUID) -> SurveyDomain:
        """Return a full survey configuration, or raise SurveyNotFoundError."""
        return SurveyDomain.from_db(await self._get_or_raise(survey_id))

    async def list_surveys(
        self,
        page: int,
        page_size: int,
        params: SurveyListingParams,
    ) -> PaginatedResult[SurveyListItemDomain]:
        """Return a paginated, filtered and sorted list of surveys."""
        page = max(1, page)
        offset = (page - 1) * page_size
        surveys, total = await self.uow.survey_repo.list(
            limit=page_size, offset=offset, params=params
        )
        return self._build_survey_list_result(surveys, total, page, page_size)

    async def list_available_surveys(
        self,
        actor: UserActor,
        page: int,
        page_size: int,
    ) -> PaginatedResult[SurveyListItemDomain]:
        """Return active surveys the caller may respond to.

        A field worker sees generic surveys plus targeted surveys aimed at one
        of their approved establishments; admins/superadmins see every active
        survey unfiltered by establishment.
        """
        actor_establishment_ids = None
        if actor.role == UserRole.FIELD_WORKER:
            relations = await self.uow.user_establishment_repo.get_by_user_id(
                actor.user_id
            )
            actor_establishment_ids = [
                r.establishment_id
                for r in relations
                if r.status == UserEstablishmentStatus.APPROVED
            ]
        page = max(1, page)
        offset = (page - 1) * page_size
        surveys, total = await self.uow.survey_repo.list_available(
            actor_establishment_ids=actor_establishment_ids,
            limit=page_size,
            offset=offset,
        )
        return self._build_survey_list_result(surveys, total, page, page_size)

    async def update(
        self, survey_id: UUID, data: SurveyUpdateRequest, actor: UserActor
    ) -> SurveyDomain:
        """Reconcile a survey to match ``data``.

        Raises:
            SurveyNotFoundError, ForbiddenError, SurveyLockedError,
            SurveyAlreadyExistsError, InvalidSurveyStructureError,
            InvalidSurveyPayloadError, EstablishmentNotFoundError.
        """
        survey = await self._get_or_raise(survey_id)
        self._assert_can_edit(actor, survey)
        new_questions = self._to_question_inputs(data.questions)
        await self._assert_editable(survey, new_questions)
        if await self.uow.survey_repo.name_exists(data.name, exclude_id=survey.id):
            raise SurveyAlreadyExistsError(data.name)
        await self._validate_structure(
            data.questions, data.scope, data.establishment_ids
        )
        try:
            survey = await self.uow.survey_repo.reconcile(
                survey,
                name=data.name,
                description=data.description,
                scope=data.scope,
                questions=new_questions,
                establishment_ids=data.establishment_ids,
            )
        except UniqueConstraintError:
            raise SurveyAlreadyExistsError(data.name)
        await self.uow.commit()
        return SurveyDomain.from_db(survey)

    async def duplicate(self, survey_id: UUID, actor: UserActor) -> SurveyDomain:
        """Deep-copy a survey under a unique ``"<name> (copy)"`` name.

        Raises:
            SurveyAlreadyExistsError: another survey grabbed the generated name
                between the availability check and the insert.
        """
        source = await self._get_or_raise(survey_id)
        self._assert_can_create(actor)
        new_name = await self._unique_copy_name(source.name)
        try:
            survey = await self.uow.survey_repo.duplicate(
                source, new_name=new_name, created_by_id=actor.user_id
            )
        except UniqueConstraintError:
            raise SurveyAlreadyExistsError(new_name)
        await self.uow.commit()
        return SurveyDomain.from_db(survey)

    async def delete(self, survey_id: UUID, actor: UserActor) -> None:
        """Delete a survey (owner or admin only, and only while unlocked)."""
        survey = await self._get_or_raise(survey_id)
        self._assert_can_edit(actor, survey)
        if survey.response_count > 0:
            raise SurveyLockedError()
        await self.uow.survey_repo.delete(survey)
        await self.uow.commit()

    async def set_active(
        self, survey_id: UUID, is_active: bool, actor: UserActor
    ) -> SurveyDomain:
        """Toggle a survey's active flag. Bypasses the edit-lock by design."""
        survey = await self._get_or_raise(survey_id)
        self._assert_can_edit(actor, survey)
        survey = await self.uow.survey_repo.update_active(survey, is_active)
        await self.uow.commit()
        return SurveyDomain.from_db(survey)
