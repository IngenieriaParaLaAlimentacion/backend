import asyncio
from datetime import date
from uuid import UUID

import structlog
from pydantic import ValidationError

from app.config.settings import settings
from app.core.interfaces.llm_client import ILlmClient
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.nutrition import MonthlyIntakeAnalysis, ReferenceProfile
from app.domain.nutrition_report import NutritionReportSortOrder, SummaryStatus
from app.domain.pagination import PaginatedResult
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    LlmClientError,
    LlmQuotaExhaustedError,
    LlmUnavailableError,
    NutritionReportConversionUnavailableError,
    NutritionReportGenerationTimeoutError,
    NutritionReportMonthNotOverError,
    NutritionReportNotFoundError,
    NutritionReportSummaryUnavailableError,
)
from app.models.establishments.establishment import Establishment
from app.models.nutrition.nutrition_report import NutritionReport
from app.reference_data.nutrition_references import REFERENCE_PROFILES
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    NutritionReportResponse,
    NutritionReportSummary,
)
from app.services.access import check_establishment_access
from app.services.nutrition.nutrition_service import NutritionService
from app.services.nutrition.report_analysis import build_analysis
from app.services.nutrition.report_summary import (
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    build_prompt,
    parse_summary,
)
from app.utils.dates import today_in_argentina

logger = structlog.get_logger()


def _log_summary_failure(
    establishment_id: UUID,
    month: date,
    reason: str,
    failures: list[str] | None = None,
) -> None:
    """Log that the AI summary could not be had, by a controlled reason code."""
    # Never the prompt, the model's text or the provider's message.
    logger.warning(
        "nutrition_report.summary_failed",
        stage="summary",
        reason=reason,
        prompt_version=PROMPT_VERSION,
        establishment_id=str(establishment_id),
        month=month.isoformat(),
        failures=failures or [],
    )


def _first_day_of(month: str) -> date:
    """Return the first day of a month formatted as ``YYYY-MM``."""
    year, number = map(int, month.split("-"))
    return date(year, number, 1)


def _profile_key(profile: ReferenceProfile) -> str:
    """Return the name a reference profile is known by."""
    return next(key for key, known in REFERENCE_PROFILES.items() if known == profile)


class NutritionReportService:
    """Monthly nutrition reports of an establishment: calculated, written up by
    the AI and saved."""

    def __init__(
        self,
        uow: IUnitOfWork,
        nutrition_service: NutritionService | None = None,
        llm: ILlmClient | None = None,
    ) -> None:
        self.uow = uow
        self.nutrition_service = nutrition_service
        self.llm = llm

    async def get_or_generate_report(
        self, establishment_id: UUID, month: str, actor: UserActor
    ) -> tuple[NutritionReport, bool]:
        """Return the report of a month, generating and saving it if there is none.

        ``month`` is formatted as ``YYYY-MM``. Returns a ``(report, created)``
        tuple: ``created`` is True for a report generated now and False for one
        already saved, including one whose unavailable summary was written again.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            NutritionReportMonthNotOverError: the month is not over yet.
            NutritionReportConversionUnavailableError: the foods received have
                no known conversion to grams.
            NutritionReportGenerationTimeoutError: the whole request exceeded
                its time budget; nothing is saved.
        """
        deadline = asyncio.timeout(settings.report_generation_timeout_seconds)
        try:
            async with deadline:
                return await self._get_or_generate(establishment_id, month, actor)
        except TimeoutError as exc:
            if not deadline.expired():
                raise
            logger.warning(
                "nutrition_report.generation_failed",
                establishment_id=str(establishment_id),
                month=month,
                reason="total_deadline_exceeded",
            )
            await self.uow.rollback()
            raise NutritionReportGenerationTimeoutError() from exc

    async def _get_or_generate(
        self, establishment_id: UUID, month: str, actor: UserActor
    ) -> tuple[NutritionReport, bool]:
        """Check access, then return the saved report or generate and save one."""
        first_day = _first_day_of(month)

        await self._check_access(establishment_id, actor)
        if first_day >= today_in_argentina().replace(day=1):
            raise NutritionReportMonthNotOverError(month)

        repo = self.uow.nutrition_report_repo
        # Held until the commit, so a concurrent request for the same month waits
        # and then finds the saved report instead of calling the AI again.
        await repo.lock(establishment_id, first_day)
        report = await repo.get_by_month(establishment_id, first_day)
        if report is None:
            report = await self._generate(establishment_id, first_day, month, actor)
            await repo.create(report)
            await self.uow.commit()
            return report, True
        if report.summary_status == SummaryStatus.UNAVAILABLE:
            await self._write_summary_again(report)
        return report, False

    async def get_report(
        self, establishment_id: UUID, month: str, actor: UserActor
    ) -> NutritionReport:
        """Return the saved report of a month, without generating anything.

        ``month`` is formatted as ``YYYY-MM``.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            NutritionReportNotFoundError: the month has no saved report.
        """
        _, report = await self._find_saved(establishment_id, month, actor)
        return report

    async def get_report_pdf(
        self, establishment_id: UUID, month: str, actor: UserActor
    ) -> bytes:
        """Return the saved report of a month as a PDF file.

        A month without intakes has no AI summary by design and is printed as it is.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            NutritionReportNotFoundError: the month has no saved report.
            NutritionReportSummaryUnavailableError: the AI could not write the
                summary yet, so the report is not complete.
        """
        # The PDF libraries are only needed from here: the app starts without them.
        from app.services.nutrition.report_pdf import render_report_pdf

        establishment, saved = await self._find_saved(establishment_id, month, actor)
        if saved.summary_status == SummaryStatus.UNAVAILABLE:
            raise NutritionReportSummaryUnavailableError(month)
        report = NutritionReportResponse.model_validate(saved)
        name = establishment.name
        # Everything printed is plain data now, so the connection goes back to the
        # pool before the rendering, which takes a while.
        await self.uow.rollback()
        return await asyncio.to_thread(render_report_pdf, report, name)

    async def list_reports(
        self,
        establishment_id: UUID,
        actor: UserActor,
        *,
        sort_order: NutritionReportSortOrder,
        page: int,
        page_size: int,
    ) -> PaginatedResult[NutritionReport]:
        """Return a page of the saved reports of an establishment, ordered by month.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        await self._check_access(establishment_id, actor)
        reports, total = await self.uow.nutrition_report_repo.list_by_establishment(
            establishment_id,
            sort_order=sort_order,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return PaginatedResult.build(
            items=reports, total=total, page=page, page_size=page_size
        )

    async def _check_access(
        self, establishment_id: UUID, actor: UserActor
    ) -> Establishment:
        """Return the establishment, once it exists and the actor may look at it."""
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        await check_establishment_access(self.uow, actor, establishment_id)
        return establishment

    async def _find_saved(
        self, establishment_id: UUID, month: str, actor: UserActor
    ) -> tuple[Establishment, NutritionReport]:
        """Return the establishment and its saved report of a month."""
        establishment = await self._check_access(establishment_id, actor)
        report = await self.uow.nutrition_report_repo.get_by_month(
            establishment_id, _first_day_of(month)
        )
        if report is None:
            raise NutritionReportNotFoundError(month)
        return establishment, report

    async def _generate(
        self, establishment_id: UUID, first_day: date, month: str, actor: UserActor
    ) -> NutritionReport:
        """Calculate the month and have the AI write its summary."""
        analysis = await self.nutrition_service.analyze_monthly_intake(
            establishment_id, first_day.year, first_day.month, actor
        )
        # A month with foods but none convertible must not be saved as empty:
        # the report would stay that way.
        if not analysis.has_data and analysis.foods_without_conversion:
            raise NutritionReportConversionUnavailableError(month)

        snapshot = build_analysis(
            analysis, self.nutrition_service.profile, await self._food_names(analysis)
        )
        summary = None
        summary_status = SummaryStatus.NOT_APPLICABLE
        if analysis.has_data:
            summary = await self._write_summary(snapshot, establishment_id, first_day)
            summary_status = (
                SummaryStatus.GENERATED if summary else SummaryStatus.UNAVAILABLE
            )
        return NutritionReport(
            establishment_id=establishment_id,
            month=first_day,
            has_data=analysis.has_data,
            analysis=snapshot.model_dump(mode="json"),
            reference_profile=_profile_key(self.nutrition_service.profile),
            summary=summary.model_dump(mode="json") if summary else None,
            summary_status=summary_status,
        )

    async def _food_names(self, analysis: MonthlyIntakeAnalysis) -> dict[UUID, str]:
        """Return the name of every food the analysis suggests or leaves out."""
        food_ids = {
            source.food_id
            for sources in analysis.top_sources.values()
            for source in sources
        } | set(analysis.foods_without_conversion)
        if not food_ids:
            return {}
        foods = await self.uow.food_repo.get_by_ids(food_ids)
        return {food.id: food.name for food in foods}

    async def _write_summary_again(self, report: NutritionReport) -> None:
        """Ask the AI again for the summary of a saved report, keeping its analysis."""
        snapshot = NutritionReportAnalysis.model_validate(report.analysis)
        summary = await self._write_summary(
            snapshot, report.establishment_id, report.month
        )
        if summary is None:
            return
        report.summary = summary.model_dump(mode="json")
        report.summary_status = SummaryStatus.GENERATED
        await self.uow.nutrition_report_repo.update(report)
        await self.uow.commit()

    async def _write_summary(
        self, snapshot: NutritionReportAnalysis, establishment_id: UUID, month: date
    ) -> NutritionReportSummary | None:
        """Return the AI's summary of the analysis, or None if it could not be had."""
        if self.llm is None:
            _log_summary_failure(establishment_id, month, "client_unavailable")
            return None
        try:
            raw = await self.llm.complete(
                prompt=build_prompt(snapshot),
                response_schema=RESPONSE_SCHEMA,
                models=settings.openrouter_report_models,
            )
            return parse_summary(raw)
        except LlmQuotaExhaustedError:
            _log_summary_failure(establishment_id, month, "quota_exhausted")
        except LlmUnavailableError:
            _log_summary_failure(establishment_id, month, "unavailable")
        except LlmClientError:
            _log_summary_failure(establishment_id, month, "provider_error")
        except ValidationError as exc:
            _log_summary_failure(
                establishment_id,
                month,
                "invalid_output",
                failures=[
                    f"{'.'.join(map(str, error['loc']))}:{error['type']}"
                    for error in exc.errors()
                ],
            )
        return None
