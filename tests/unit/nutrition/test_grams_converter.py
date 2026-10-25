import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import (
    ConversionFactors,
    ConversionFailure,
    Converted,
    Unconverted,
)
from app.services.nutrition import GramsConverter


async def test_a_loaded_converter_converts_each_food_with_its_own_factors():
    """Each food converts from its own base unit with the factors stored for it,
    and one missing its factor reports why."""
    rice_id, milk_id, eggs_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    foods = [
        SimpleNamespace(id=rice_id, base_unit=MeasurementUnit.KILOGRAMOS),
        SimpleNamespace(id=milk_id, base_unit=MeasurementUnit.LITROS),
        SimpleNamespace(id=eggs_id, base_unit=MeasurementUnit.UNIDADES),
    ]
    uow = AsyncMock()
    # Made-up test data, not real equivalences.
    uow.food_equivalence_repo.get_factors_by_food_ids = AsyncMock(
        return_value={
            rice_id: ConversionFactors(),
            milk_id: ConversionFactors(density_g_ml=Decimal("1.03")),
            eggs_id: ConversionFactors(),
        }
    )

    converter = await GramsConverter.load(uow, foods)

    assert converter.convert(rice_id, Decimal("2")) == Converted(Decimal("2000"))
    assert converter.convert(milk_id, Decimal("1")) == Converted(Decimal("1030"))
    assert converter.convert(eggs_id, Decimal("12")) == Unconverted(
        ConversionFailure.MISSING_UNIT_WEIGHT
    )
    # One query for all the foods, whatever the number of conversions.
    uow.food_equivalence_repo.get_factors_by_food_ids.assert_awaited_once_with(
        [rice_id, milk_id, eggs_id]
    )


async def test_converting_a_food_that_was_not_loaded_is_an_error():
    uow = AsyncMock()
    uow.food_equivalence_repo.get_factors_by_food_ids = AsyncMock(return_value={})

    converter = await GramsConverter.load(uow, [])

    with pytest.raises(KeyError):
        converter.convert(uuid.uuid4(), Decimal("1"))
