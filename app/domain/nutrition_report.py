from enum import StrEnum
from typing import NamedTuple

from app.domain.nutrition import (
    GapaGroup,
    LimitedNutrient,
    Macronutrient,
    PrioritizedNutrient,
)

# Longest text of a summary section or of one of its list items, in characters.
SUMMARY_TEXT_MAX_LENGTH = 1500

# Most items a list of the summary may hold.
SUMMARY_MAX_ITEMS = 7


# Shown with every report. It is fixed text: the AI does not write it and it is not
# stored, so changing it applies to the reports already generated.
SCOPE_NOTE = (
    "Este informe evalúa el equilibrio nutricional de los alimentos que llegaron "
    "al comedor durante el mes. No conoce la dieta completa de los chicos, no "
    "indica si la cantidad alcanza y no reemplaza la evaluación de un nutricionista."
)


class NutritionReportSortOrder(StrEnum):
    """Order in which the reports of an establishment are listed, by month."""

    MONTH_DESC = "month_desc"
    MONTH_ASC = "month_asc"


class SummaryStatus(StrEnum):
    """What became of the AI-written summary of a report."""

    GENERATED = "generated"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class Label(NamedTuple):
    """The name and unit shown for a nutrient."""

    name: str
    unit: str


# Spanish names for the codes a report stores. Units are the catalog's.
NUTRIENT_LABELS: dict[PrioritizedNutrient, Label] = {
    PrioritizedNutrient.CALCIUM: Label("Calcio", "mg"),
    PrioritizedNutrient.VITAMIN_A: Label("Vitamina A (RAE)", "µg"),
    PrioritizedNutrient.FOLATE: Label("Folato (EFD)", "µg"),
    PrioritizedNutrient.VITAMIN_B12: Label("Vitamina B-12", "µg"),
    PrioritizedNutrient.VITAMIN_C: Label("Vitamina C", "mg"),
    PrioritizedNutrient.IRON: Label("Hierro", "mg"),
    PrioritizedNutrient.ZINC: Label("Zinc", "mg"),
}

LIMIT_LABELS: dict[LimitedNutrient, Label] = {
    LimitedNutrient.FIBER: Label("Fibra alimentaria", "g"),
    LimitedNutrient.SODIUM: Label("Sodio", "mg"),
    LimitedNutrient.SATURATED_FAT: Label("Saturados", "g"),
    LimitedNutrient.ADDED_SUGAR: Label("Azúcar agregado", "g"),
}

MACRO_LABELS: dict[Macronutrient, str] = {
    Macronutrient.PROTEIN: "Proteínas",
    Macronutrient.LIPIDS: "Lípidos totales",
    Macronutrient.CARBOHYDRATES: "Carbohidratos totales",
}

GAPA_GROUP_LABELS: dict[GapaGroup, str] = {
    GapaGroup.FRUITS_AND_VEGETABLES: "Verduras y frutas",
    GapaGroup.LEGUMES_CEREALS_BREAD_PASTA: "Legumbres, cereales, papa, pan y pastas",
    GapaGroup.DAIRY: "Leche, yogur y quesos",
    GapaGroup.MEAT_AND_EGGS: "Carnes y huevos",
    GapaGroup.OILS_NUTS_AND_SEEDS: "Aceites, frutas secas y semillas",
    GapaGroup.OPTIONAL: "Consumo opcional",
}

# Notes on how a reference was set; the reference profile has them in English.
NUTRIENT_NOTES: dict[PrioritizedNutrient, str] = {
    PrioritizedNutrient.IRON: "Hierro: la referencia considera una biodisponibilidad "
    "del 10 %.",
    PrioritizedNutrient.ZINC: "Zinc: la referencia considera una biodisponibilidad "
    "moderada.",
}
