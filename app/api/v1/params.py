from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Query

from app.domain.establishment import EstablishmentListingParams, EstablishmentSortOrder
from app.domain.measurement import MeasurementListingParams, MeasurementSortOrder
from app.exceptions.domain_exceptions import InvalidListingFilterError


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
