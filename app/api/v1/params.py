from dataclasses import dataclass
from typing import Annotated

from fastapi import Query

from app.domain.establishment import EstablishmentListingParams, EstablishmentSortOrder


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
