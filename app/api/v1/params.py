from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Query, status

from app.domain.establishment import (
    EstablishmentCreationRequestListingParams,
    EstablishmentCreationRequestSortOrder,
    EstablishmentListingParams,
    EstablishmentRequestStatus,
    EstablishmentSortOrder,
    UserEstablishmentStatus,
)
from app.domain.establishment_dashboard import (
    EstablishmentFieldWorkerListingParams,
    EstablishmentSubjectListingParams,
    EstablishmentSubjectSortOrder,
)
from app.domain.food_catalog import (
    FoodCategoryListingParams,
    FoodListingParams,
    FoodSortOrder,
)
from app.domain.measurement import MeasurementListingParams, MeasurementSortOrder
from app.domain.subject import Sex, SubjectListingParams, SubjectSortOrder
from app.domain.survey import (
    NAME_MAX,
    SurveyListingParams,
    SurveyResponseTarget,
    SurveySortOrder,
)
from app.domain.survey_response import (
    SurveyResponseListingParams,
    SurveyResponseSortOrder,
    SurveyResponseSummaryParams,
)
from app.exceptions.domain_exceptions import (
    InvalidAgeRangeError,
    InvalidDateRangeError,
    InvalidNumberRangeError,
)

AUTH_RESPONSES: dict[int | str, dict[str, str]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Missing or invalid authentication token"
    },
    status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
}


def _validate_date_range(
    start: date | None, end: date | None, field_prefix: str
) -> None:
    """Raise InvalidDateRangeError if ``start`` is after ``end``.

    Accepts plain dates or full timestamps (``datetime`` is a subclass of
    ``date``), so it covers both date-only and datetime-range filters.
    """
    if start is not None and end is not None and start > end:
        raise InvalidDateRangeError(
            f"{field_prefix}_from cannot be after {field_prefix}_to"
        )


def _validate_number_range(
    start: int | None, end: int | None, field_prefix: str
) -> None:
    """Raise InvalidNumberRangeError if ``start`` is greater than ``end``."""
    if start is not None and end is not None and start > end:
        raise InvalidNumberRangeError(
            f"{field_prefix}_from cannot be greater than {field_prefix}_to"
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
        """Raise InvalidAgeRangeError if the age bounds are inverted, or
        InvalidDateRangeError if the measurement-date bounds are.
        """
        if (
            self.min_age is not None
            and self.max_age is not None
            and self.min_age > self.max_age
        ):
            raise InvalidAgeRangeError("min_age cannot be greater than max_age")

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
class EstablishmentSubjectsQuery:
    search: Annotated[
        str | None,
        Query(
            max_length=100,
            description="Partial match on name/last name, exact match on DNI.",
        ),
    ] = None
    sort_order: EstablishmentSubjectSortOrder = (
        EstablishmentSubjectSortOrder.MEASURED_AT_DESC
    )

    def to_domain(self) -> EstablishmentSubjectListingParams:
        return EstablishmentSubjectListingParams(
            search=self.search,
            sort_order=self.sort_order,
        )


@dataclass
class EstablishmentFieldWorkersQuery:
    search: Annotated[
        str | None,
        Query(max_length=100, description="Partial match on name, last name or email."),
    ] = None
    relation_status: Annotated[
        list[UserEstablishmentStatus] | None,
        Query(
            description="Enrollment statuses to include. Defaults to approved "
            "enrollments when omitted."
        ),
    ] = None

    def to_domain(self) -> EstablishmentFieldWorkerListingParams:
        return EstablishmentFieldWorkerListingParams(
            search=self.search,
            relation_status=self.relation_status,
        )


@dataclass
class FoodListingQuery:
    search: Annotated[str | None, Query(max_length=200)] = None
    category_id: Annotated[UUID | None, Query()] = None
    sort_order: FoodSortOrder = FoodSortOrder.NAME_ASC

    def to_domain(self) -> FoodListingParams:
        return FoodListingParams(
            search=self.search,
            category_id=self.category_id,
            sort_order=self.sort_order,
        )


@dataclass
class FoodCategoryListingQuery:
    sort_order: FoodSortOrder = FoodSortOrder.NAME_ASC

    def to_domain(self) -> FoodCategoryListingParams:
        return FoodCategoryListingParams(sort_order=self.sort_order)


@dataclass
class SurveyListingQuery:
    search: Annotated[str | None, Query(max_length=NAME_MAX)] = None
    created_by: Annotated[UUID | None, Query()] = None
    response_target: Annotated[SurveyResponseTarget | None, Query()] = None
    is_active: Annotated[bool | None, Query()] = None
    sort_order: SurveySortOrder = SurveySortOrder.NEWEST

    def to_domain(self) -> SurveyListingParams:
        return SurveyListingParams(
            search=self.search,
            created_by=self.created_by,
            response_target=self.response_target,
            is_active=self.is_active,
            sort_order=self.sort_order,
        )


@dataclass
class SurveyResponseListingQuery(LocationQuery):
    subject_id: Annotated[UUID | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    event_at_from: Annotated[datetime | None, Query()] = None
    event_at_to: Annotated[datetime | None, Query()] = None
    response_number: Annotated[int | None, Query(ge=1, le=999_999)] = None
    response_number_from: Annotated[int | None, Query(ge=1, le=999_999)] = None
    response_number_to: Annotated[int | None, Query(ge=1, le=999_999)] = None
    sort_order: SurveyResponseSortOrder = SurveyResponseSortOrder.EVENT_AT_DESC

    def validate(self) -> None:
        """Raise when the date or response-number bounds are inverted."""
        _validate_date_range(self.event_at_from, self.event_at_to, "event_at")
        _validate_number_range(
            self.response_number_from, self.response_number_to, "response_number"
        )

    def to_domain(self) -> SurveyResponseListingParams:
        return SurveyResponseListingParams(
            subject_id=self.subject_id,
            establishment_id=self.establishment_id,
            event_at_from=self.event_at_from,
            event_at_to=self.event_at_to,
            city=self.city,
            province=self.province,
            response_number=self.response_number,
            response_number_from=self.response_number_from,
            response_number_to=self.response_number_to,
            sort_order=self.sort_order,
        )


@dataclass
class SurveyResponseSummaryQuery(LocationQuery):
    survey_id: Annotated[UUID | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    event_at_from: Annotated[datetime | None, Query()] = None
    event_at_to: Annotated[datetime | None, Query()] = None

    def validate(self) -> None:
        """Raise InvalidDateRangeError if the date bounds are inverted."""
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


@dataclass
class SubjectListingQuery:
    search: Annotated[str | None, Query(max_length=100)] = None
    birth_date_from: Annotated[date | None, Query()] = None
    birth_date_to: Annotated[date | None, Query()] = None
    establishment_id: Annotated[UUID | None, Query()] = None
    is_rural: Annotated[bool | None, Query()] = None
    is_indigenous: Annotated[bool | None, Query()] = None
    sex: Annotated[Sex | None, Query()] = None
    sort_order: SubjectSortOrder = SubjectSortOrder.CREATED_AT_DESC

    def validate(self) -> None:
        """Raise InvalidDateRangeError if the date bounds are inverted."""
        _validate_date_range(self.birth_date_from, self.birth_date_to, "birth_date")

    def to_domain(self) -> SubjectListingParams:
        return SubjectListingParams(
            search=self.search,
            birth_date_from=self.birth_date_from,
            birth_date_to=self.birth_date_to,
            establishment_id=self.establishment_id,
            is_rural=self.is_rural,
            is_indigenous=self.is_indigenous,
            sex=self.sex,
            sort_order=self.sort_order,
        )


@dataclass
class EstablishmentCreationRequestListingQuery(LocationQuery):
    search: Annotated[
        str | None,
        Query(
            max_length=100,
            description="Partial match on the reported name/address, or on the "
            "requester's name, last name or email.",
        ),
    ] = None
    status: Annotated[
        EstablishmentRequestStatus | None,
        Query(description="Filter by review status."),
    ] = None
    sort_order: EstablishmentCreationRequestSortOrder = (
        EstablishmentCreationRequestSortOrder.OLDEST
    )

    def to_domain(self) -> EstablishmentCreationRequestListingParams:
        return EstablishmentCreationRequestListingParams(
            search=self.search,
            city=self.city,
            province=self.province,
            status=self.status,
            sort_order=self.sort_order,
        )
