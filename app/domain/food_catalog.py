from enum import Enum


class MeasurementUnit(str, Enum):
    """Unit a food's stock quantity is persisted in."""

    UNIDADES = "unidades"
    KILOGRAMOS = "kilogramos"
    LITROS = "litros"


class NutrientGroup(str, Enum):
    """Which of SARA 2's two composition tables a nutrient belongs to."""

    MACRONUTRIENT = "macronutrient"
    VITAMIN = "vitamin"
    MINERAL = "mineral"
    FATTY_ACID = "fatty_acid"
