from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class MealType(StrEnum):
    """Meal of the day a recipe is planned for."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SNACK = "snack"
    DINNER = "dinner"


class GapaGroup(StrEnum):
    """The six GAPA food groups; values are the codes of ``gapa_food_categories``."""

    FRUITS_AND_VEGETABLES = "verduras_y_frutas"
    LEGUMES_CEREALS_BREAD_PASTA = "legumbres_cereales_papa_pan_y_pastas"
    DAIRY = "leche_yogur_y_quesos"
    MEAT_AND_EGGS = "carnes_y_huevos"
    OILS_NUTS_AND_SEEDS = "aceites_frutas_secas_y_semillas"
    OPTIONAL = "consumo_opcional"


class PrioritizedNutrient(StrEnum):
    """The micronutrients that make up the composite adequacy indicator."""

    CALCIUM = "calcio"
    VITAMIN_A = "vitamina_a"
    FOLATE = "folato"
    VITAMIN_B12 = "vitamina_b12"
    VITAMIN_C = "vitamina_c"
    IRON = "hierro"
    ZINC = "zinc"


class Macronutrient(StrEnum):
    """Macronutrients whose share of the energy is checked against a range."""

    PROTEIN = "proteinas"
    LIPIDS = "lipidos"
    CARBOHYDRATES = "carbohidratos"


class LimitedNutrient(StrEnum):
    """Nutrients reported against a limit; values are their catalog codes."""

    FIBER = "fibra_alimentaria"
    SODIUM = "sodio"
    SATURATED_FAT = "saturados"
    ADDED_SUGAR = "azucar_agregado"


class UnmetConstraintKind(StrEnum):
    """Rule a suggested recipe could not satisfy."""

    MACRO_BELOW_MIN = "macro_below_min"
    MACRO_ABOVE_MAX = "macro_above_max"
    GAPA_GROUP_BELOW_MIN = "gapa_group_below_min"
    STOCK_INSUFFICIENT = "stock_insufficient"


@dataclass
class FoodComposition:
    """What the calculation needs to know about one catalog food.

    ``per_100g`` maps a catalog nutrient code to its amount per 100 g; a nutrient
    the catalog has no reading for is absent. ``gapa_group`` is None when the food
    belongs to no group.
    """

    food_id: UUID
    gapa_group: GapaGroup | None
    per_100g: dict[str, float]


@dataclass
class StockedFood:
    """A food a recipe may use and the grams of it available."""

    composition: FoodComposition
    stock_grams: float


@dataclass
class FoodQuantity:
    """An amount of one catalog food, in grams."""

    food_id: UUID
    grams: float


@dataclass
class NutrientAdequacy:
    """How much of a prioritized nutrient a food combination covers.

    ``amount_per_1000_kcal`` is in the nutrient's own unit. ``adequacy_capped``
    is ``adequacy_uncapped`` limited to 1.
    """

    nutrient: PrioritizedNutrient
    amount_per_1000_kcal: float
    adequacy_uncapped: float
    adequacy_capped: float


@dataclass
class LimitIndicator:
    """Intake of fiber, sodium, saturated fat or added sugar, shown as information.

    ``code`` is the nutrient code in the catalog.
    """

    code: str
    amount_per_1000_kcal: float


@dataclass
class NutritionIndicators:
    """Balance indicators of a food combination.

    Everything but ``has_data`` and ``warnings`` is empty when ``has_data`` is
    false, which happens when the foods carry no energy. Macro and group shares
    are fractions of the energy (0 to 1).
    """

    has_data: bool
    energy_kcal: float | None = None
    nutrients: list[NutrientAdequacy] = field(default_factory=list)
    mean_adequacy_ratio: float | None = None
    macro_energy_share: dict[Macronutrient, float] = field(default_factory=dict)
    gapa_energy_share: dict[GapaGroup, float] = field(default_factory=dict)
    limit_indicators: list[LimitIndicator] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RecipeRequest:
    """What the caller asks a recipe to be built from.

    ``children_count`` is how many children the recipe has to feed.
    """

    food_ids: list[UUID]
    children_count: int
    meal_type: MealType


@dataclass
class UnmetConstraint:
    """A rule the recipe could not satisfy.

    ``subject`` is the macronutrient or GAPA group code concerned, or ``energy``
    for insufficient stock. ``amount`` is how much was missing or in excess, in
    ``unit`` (``kcal`` or ``g``).
    """

    kind: UnmetConstraintKind
    subject: str
    amount: float
    unit: str


@dataclass
class RecipeSolution:
    """The quantities chosen for a recipe and how balanced they are.

    ``quantities`` are grams for the whole recipe. ``target_energy_kcal`` is the
    energy asked for; ``energy_kcal`` is the energy actually planned, lower when
    the stock falls short. ``has_data`` is false when the stock carries no energy.
    """

    has_data: bool
    quantities: list[FoodQuantity] = field(default_factory=list)
    target_energy_kcal: float | None = None
    energy_kcal: float | None = None
    indicators: NutritionIndicators | None = None
    unmet_constraints: list[UnmetConstraint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MacroOutOfRange:
    """A macronutrient whose share of the energy falls outside its range."""

    macro: Macronutrient
    energy_share: float
    min_share: float
    max_share: float


@dataclass
class FoodSource:
    """A catalog food and how much of a nutrient it gives per 100 kcal."""

    food_id: UUID
    amount_per_100_kcal: float


@dataclass
class MonthlyIntakeAnalysis:
    """Balance of everything an establishment received in a calendar month.

    ``has_data`` is false when the month has no intakes with energy. A nutrient a
    food has no reading for counts as 0, so it can be in ``nutrients_at_risk``
    because of a gap in the catalog; the matching entry of ``warnings`` says so.
    """

    has_data: bool
    indicators: NutritionIndicators | None = None
    nutrients_at_risk: list[PrioritizedNutrient] = field(default_factory=list)
    macros_out_of_range: list[MacroOutOfRange] = field(default_factory=list)
    missing_gapa_groups: list[GapaGroup] = field(default_factory=list)
    top_sources: dict[PrioritizedNutrient, list[FoodSource]] = field(
        default_factory=dict
    )
    warnings: list[str] = field(default_factory=list)
