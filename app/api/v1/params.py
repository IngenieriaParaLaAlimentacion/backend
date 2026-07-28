from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Query, status

from app.domain.establishment import EstablishmentListingParams, EstablishmentSortOrder
from app.domain.measurement import MeasurementListingParams, MeasurementSortOrder
from app.domain.survey import (
    NAME_MAX,
    SurveyListingParams,
    SurveyScope,
    SurveySortOrder,
)
from app.domain.survey_response import (
    SurveyResponseListingParams,
    SurveyResponseSummaryParams,
)
from app.exceptions.domain_exceptions import InvalidListingFilterError

AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Missing or invalid authentication token"
    },
    status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
}


def _validate_date_range(
    start: datetime | None, end: datetime | None, field_prefix: str
) -> None:
    """Helper to validate that a 'from' date is not after a 'to' date."""
    if start is not None and end is not None and start > end:
        raise InvalidListingFilterError(
            f"{field_prefix}_from cannot be after {field_prefix}_to"
        )


@dataclass
class LocationQuery:
    """Base query params for endpoints that filter by location."""

    city: Annotated[str | None, Query(max_length=100)] = None
    province: Annotated[str | None, Query(max_length=100)] = None


@dataclass
class PaginatedQueryParams:
    page: Annotated[int, Query(ge=1, description="Page number, starting at 1.")] = 1
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Results per page (max 100).")
    ] = 20


@dataclass
class EstablishmentListingQuery(LocationQuery):
    search: Annotated[str | None, Query(max_length=100)] = None
    sort_order: EstablishmentSortOrder = EstablishmentSortOrder.NEWEST

    def to_domain(self) -> EstablishmentListingParams:
        return EstablishmentListingParams(
            search=self.search,
            city=self.city,
            province=self.province,
            sort_order=self.sort_order,
        )


@dataclass
class MeasurementListingQuery(LocationQuery):
    subject_id: Annotated[UUID | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    responsible_id: Annotated[UUID | None, Query()] = None
    measured_from: Annotated[datetime | None, Query()] = None
    measured_to: Annotated[datetime | None, Query()] = None
    min_age: Annotated[int | None, Query(ge=0, le=150)] = None
    max_age: Annotated[int | None, Query(ge=0, le=150)] = None
    sort_order: MeasurementSortOrder = MeasurementSortOrder.DATE_DESC

    def validate(self) -> None:
        if (
            self.min_age is not None
            and self.max_age is not None
            and self.min_age > self.max_age
        ):
            raise InvalidListingFilterError("min_age cannot be greater than max_age")

        _validate_date_range(self.measured_from, self.measured_to, "measured")

    def to_domain(self) -> MeasurementListingParams:
        return MeasurementListingParams(
            subject_id=self.subject_id,
            establishment_id=self.establishment_id,
            city=self.city,
            province=self.province,
            responsible_id=self.responsible_id,
            measured_from=self.measured_from,
            measured_to=self.measured_to,
            min_age=self.min_age,
            max_age=self.max_age,
            sort_order=self.sort_order,
        )


@dataclass
class SurveyListingQuery:
    search: Annotated[str | None, Query(max_length=NAME_MAX)] = None
    created_by: Annotated[UUID | None, Query()] = None
    scope: Annotated[SurveyScope | None, Query()] = None
    is_active: Annotated[bool | None, Query()] = None
    sort_order: SurveySortOrder = SurveySortOrder.NEWEST

    def to_domain(self) -> SurveyListingParams:
        return SurveyListingParams(
            search=self.search,
            created_by=self.created_by,
            scope=self.scope,
            is_active=self.is_active,
            sort_order=self.sort_order,
        )


@dataclass
class SurveyResponseListingQuery(LocationQuery):
    establishment_id: Annotated[UUID | None, Query()] = None
    event_at_from: Annotated[datetime | None, Query()] = None
    event_at_to: Annotated[datetime | None, Query()] = None

    def validate(self) -> None:
        _validate_date_range(self.event_at_from, self.event_at_to, "event_at")

    def to_domain(self) -> SurveyResponseListingParams:
        return SurveyResponseListingParams(
            establishment_id=self.establishment_id,
            event_at_from=self.event_at_from,
            event_at_to=self.event_at_to,
            city=self.city,
            province=self.province,
        )


@dataclass
class SurveyResponseSummaryQuery(LocationQuery):
    survey_id: Annotated[UUID | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    event_at_from: Annotated[datetime | None, Query()] = None
    event_at_to: Annotated[datetime | None, Query()] = None

    def validate(self) -> None:
        _validate_date_range(self.event_at_from, self.event_at_to, "event_at")

    def to_domain(self) -> SurveyResponseSummaryParams:
        return SurveyResponseSummaryParams(
            survey_id=self.survey_id,
            establishment_id=self.establishment_id,
            event_at_from=self.event_at_from,
            event_at_to=self.event_at_to,
            city=self.city,
            province=self.province,
        )
