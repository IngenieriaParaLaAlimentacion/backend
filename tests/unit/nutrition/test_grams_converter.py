import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import (
    ConversionFactors,
    ConversionFailure,
    Converted,
    Unconverted,
)
from app.services.nutrition import GramsConverter


async def test_to_grams_converts_each_food_with_its_own_factors():
    """Each food converts from its own base unit with the factors stored for it,
    and one missing its factor reports why."""
    rice_id, milk_id, eggs_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    uow = AsyncMock()
    # Made-up test data, not real equivalences.
    uow.food_equivalence_repo.get_factors_by_food_ids = AsyncMock(
        return_value={
            rice_id: ConversionFactors(),
            milk_id: ConversionFactors(density_g_ml=Decimal("1.03")),
            eggs_id: ConversionFactors(),
        }
    )

    result = await GramsConverter(uow).to_grams(
        {rice_id: Decimal("2"), milk_id: Decimal("1"), eggs_id: Decimal("12")},
        {
            rice_id: MeasurementUnit.KILOGRAMOS,
            milk_id: MeasurementUnit.LITROS,
            eggs_id: MeasurementUnit.UNIDADES,
        },
    )

    assert result == {
        rice_id: Converted(Decimal("2000")),
        milk_id: Converted(Decimal("1030")),
        eggs_id: Unconverted(ConversionFailure.MISSING_UNIT_WEIGHT),
    }
