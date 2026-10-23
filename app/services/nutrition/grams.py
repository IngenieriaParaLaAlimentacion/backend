from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import ConversionResult
from app.domain.unit_conversion import to_grams as convert_to_grams


class GramsConverter:
    """Converts quantities of catalog foods from their base unit to grams."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def to_grams(
        self,
        quantities: Mapping[UUID, Decimal],
        base_units: Mapping[UUID, MeasurementUnit],
    ) -> dict[UUID, ConversionResult]:
        """Return each food's quantity in grams, or why it could not be converted.

        ``base_units`` holds the base unit of every food in ``quantities``. The
        factors of all the foods are read in one query.
        """
        factors = await self.uow.food_equivalence_repo.get_factors_by_food_ids(
            list(quantities)
        )
        return {
            food_id: convert_to_grams(quantity, base_units[food_id], factors[food_id])
            for food_id, quantity in quantities.items()
        }
