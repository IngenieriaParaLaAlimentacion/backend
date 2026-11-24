from collections.abc import Iterable
from dataclasses import replace
from typing import TypeVar
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.measurement import MeasurementListingParams
from app.domain.measurement_assessment import Assessment, Indicator
from app.domain.subject import SubjectListingParams
from app.exceptions.domain_exceptions import FilterNotApplicableError
from app.reference_data.sap_reference import visible_ruleset

ListingParams = TypeVar("ListingParams", MeasurementListingParams, SubjectListingParams)


async def begin_assessment_read(uow: IUnitOfWork) -> None:
    """Keep the raw measurements and exposed assessments on one snapshot."""
    if visible_ruleset() is not None:
        await uow.begin_consistent_read()


def assessment_filter_options() -> dict[Indicator, tuple[str, ...]] | None:
    """Return the visible ruleset's classification vocabulary."""
    ruleset = visible_ruleset()
    if ruleset is None:
        return None
    return {indicator: ruleset.classifications(indicator) for indicator in Indicator}


def resolve_assessment_filters(params: ListingParams) -> ListingParams:
    """Validate an indicator filter and bind it to the visible ruleset."""
    if params.indicator is None:
        if params.classification is not None:
            raise FilterNotApplicableError("Classification requires an indicator.")
        return params

    ruleset = visible_ruleset()
    if ruleset is None:
        raise FilterNotApplicableError("Assessment filters are unavailable.")
    if (
        params.classification is not None
        and params.classification not in ruleset.classifications(params.indicator)
    ):
        raise FilterNotApplicableError(
            "The classification does not belong to the selected indicator."
        )
    return replace(params, ruleset_version=ruleset.version)


async def assessments_by_id(
    uow: IUnitOfWork, ids: Iterable[UUID]
) -> dict[UUID, tuple[Assessment, ...]]:
    """Load the assessments from the active read version in one query."""
    ruleset = visible_ruleset()
    if ruleset is None:
        return {}
    measurement_ids = list(ids)
    if not measurement_ids:
        return {}
    return await uow.measurement_assessment_repo.list_for_measurements(
        measurement_ids, ruleset.version
    )
