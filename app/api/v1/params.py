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


@dataclass
class PaginatedQueryParams:
    page: Annotated[int, Query(ge=1, description="Page number, starting at 1.")] = 1
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Results per page (max 100).")
    ] = 20


@dataclass
class EstablishmentListingQuery:
    search: Annotated[str | None, Query(max_length=100)] = None
    city: Annotated[str | None, Query(max_length=100)] = None
    province: Annotated[str | None, Query(max_length=100)] = None
    sort_order: EstablishmentSortOrder = EstablishmentSortOrder.NEWEST

    def to_domain(self) -> EstablishmentListingParams:
        return EstablishmentListingParams(
            search=self.search,
            city=self.city,
            province=self.province,
            sort_order=self.sort_order,
        )


@dataclass
class MeasurementListingQuery:
    subject_id: Annotated[UUID | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    city: Annotated[str | None, Query(max_length=100)] = None
    province: Annotated[str | None, Query(max_length=100)] = None
    responsible_id: Annotated[UUID | None, Query()] = None
    measured_from: Annotated[datetime | None, Query()] = None
    measured_to: Annotated[datetime | None, Query()] = None
    min_age: Annotated[int | None, Query(ge=0, le=150)] = None
    max_age: Annotated[int | None, Query(ge=0, le=150)] = None
    sort_order: MeasurementSortOrder = MeasurementSortOrder.DATE_DESC

    def validate(self) -> None:
        """Validate cross-field constraints. Raises InvalidListingFilterError."""
        if (
            self.min_age is not None
            and self.max_age is not None
            and self.min_age > self.max_age
        ):
            raise InvalidListingFilterError("min_age cannot be greater than max_age")
        if (
            self.measured_from is not None
            and self.measured_to is not None
            and self.measured_from > self.measured_to
        ):
            raise InvalidListingFilterError("measured_from cannot be after measured_to")

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
class SurveyResponseListingQuery:
    establishment_id: Annotated[UUID | None, Query()] = None
    event_at_from: Annotated[datetime | None, Query()] = None
    event_at_to: Annotated[datetime | None, Query()] = None
    city: Annotated[str | None, Query(max_length=100)] = None
    province: Annotated[str | None, Query(max_length=100)] = None

    def validate(self) -> None:
        """Validate cross-field constraints. Raises InvalidListingFilterError."""
        if (
            self.event_at_from is not None
            and self.event_at_to is not None
            and self.event_at_from > self.event_at_to
        ):
            raise InvalidListingFilterError("event_at_from cannot be after event_at_to")

    def to_domain(self) -> SurveyResponseListingParams:
        return SurveyResponseListingParams(
            establishment_id=self.establishment_id,
            event_at_from=self.event_at_from,
            event_at_to=self.event_at_to,
            city=self.city,
            province=self.province,
        )


@dataclass
class SurveyResponseSummaryQuery:
    survey_id: Annotated[UUID | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    event_at_from: Annotated[datetime | None, Query()] = None
    event_at_to: Annotated[datetime | None, Query()] = None
    city: Annotated[str | None, Query(max_length=100)] = None
    province: Annotated[str | None, Query(max_length=100)] = None

    def validate(self) -> None:
        if (
            self.event_at_from is not None
            and self.event_at_to is not None
            and self.event_at_from > self.event_at_to
        ):
            raise InvalidListingFilterError("event_at_from cannot be after event_at_to")

    def to_domain(self) -> SurveyResponseSummaryParams:
        return SurveyResponseSummaryParams(
            survey_id=self.survey_id,
            establishment_id=self.establishment_id,
            event_at_from=self.event_at_from,
            event_at_to=self.event_at_to,
            city=self.city,
            province=self.province,
        )
