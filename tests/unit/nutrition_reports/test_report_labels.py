import pytest

from app.domain.nutrition import (
    GapaGroup,
    LimitedNutrient,
    Macronutrient,
    PrioritizedNutrient,
)
from app.domain.nutrition_report import (
    GAPA_GROUP_LABELS,
    LIMIT_LABELS,
    MACRO_LABELS,
    NUTRIENT_LABELS,
    NUTRIENT_NOTES,
)
from app.reference_data.nutrition_references import NINO_7_9
from tests.unit.nutrition.helpers import read_reference_csv

# The report names these two nutrients differently from the catalog.
CATALOG_CODE = {"vitamina_a": "vitamina_a_rae", "folato": "folato_efd"}


@pytest.mark.parametrize(
    ("labels", "codes"),
    [
        (NUTRIENT_LABELS, PrioritizedNutrient),
        (LIMIT_LABELS, LimitedNutrient),
        (MACRO_LABELS, Macronutrient),
        (GAPA_GROUP_LABELS, GapaGroup),
    ],
    ids=["nutrients", "limits", "macros", "gapa-groups"],
)
def test_every_code_a_report_can_store_has_a_label(labels, codes):
    assert set(labels) == set(codes)


def test_units_are_the_catalogs():
    catalog = {row["code"]: row["unit"] for row in read_reference_csv("nutrients.csv")}
    shown = {
        CATALOG_CODE.get(code.value, code.value): label.unit
        for code, label in {**NUTRIENT_LABELS, **LIMIT_LABELS}.items()
    }

    assert shown == {code: catalog[code] for code in shown}


def test_gapa_group_names_are_the_catalogs():
    catalog = {
        row["code"]: row["name"]
        for row in read_reference_csv("gapa_food_categories.csv")
    }

    assert {group.value: name for group, name in GAPA_GROUP_LABELS.items()} == catalog


def test_only_the_nutrients_whose_reference_has_a_note_carry_one():
    with_note = {
        nutrient
        for nutrient, reference in NINO_7_9.nutrients.items()
        if reference.bioavailability_note
    }

    assert set(NUTRIENT_NOTES) == with_note
