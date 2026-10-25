from datetime import date
from uuid import UUID

import structlog
from pydantic import ValidationError

from app.core.interfaces.llm_client import ILlmClient
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.nutrition import MonthlyIntakeAnalysis, ReferenceProfile
from app.domain.nutrition_report import SummaryStatus
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    LlmClientError,
    NutritionReportConversionUnavailableError,
    NutritionReportMonthNotOverError,
)
from app.models.nutrition.nutrition_report import NutritionReport
from app.reference_data.nutrition_references import REFERENCE_PROFILES
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
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


def _profile_key(profile: ReferenceProfile) -> str:
    """Return the name a reference profile is known by."""
    return next(key for key, known in REFERENCE_PROFILES.items() if known == profile)


class NutritionReportService:
    """Monthly nutrition reports of an establishment: calculated, written up by
    the AI and saved."""

    def __init__(
        self,
        uow: IUnitOfWork,
        nutrition: NutritionService,
        llm: ILlmClient | None = None,
    ) -> None:
        self.uow = uow
        self.nutrition = nutrition
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
        """
        year, number = map(int, month.split("-"))
        first_day = date(year, number, 1)

        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_establishment_access(self.uow, actor, establishment_id)
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

    async def _generate(
        self, establishment_id: UUID, first_day: date, month: str, actor: UserActor
    ) -> NutritionReport:
        """Calculate the month and have the AI write its summary."""
        analysis = await self.nutrition.analyze_monthly_intake(
            establishment_id, first_day.year, first_day.month, actor
        )
        # A month with foods but none convertible must not be saved as empty:
        # the report would stay that way.
        if not analysis.has_data and analysis.foods_without_conversion:
            raise NutritionReportConversionUnavailableError(month)

        snapshot = build_analysis(
            analysis, self.nutrition.profile, await self._food_names(analysis)
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
            reference_profile=_profile_key(self.nutrition.profile),
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
        try:
            raw = await self.llm.complete(
                prompt=build_prompt(snapshot), response_schema=RESPONSE_SCHEMA
            )
            return parse_summary(raw)
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
