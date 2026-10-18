from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.food_catalog import MeasurementUnit
from app.domain.nutrition import MealType, NutritionIndicators, UnmetConstraint

ChildrenCount = Annotated[int, Field(strict=True, ge=1, le=10000)]


class CulturalIdentity(StrEnum):
    """Supported establishment cultural identities."""

    PARAGUAYAN = "paraguayan"
    BOLIVIAN = "bolivian"


class RecommendationInput(BaseModel):
    """Fixed input for a recommendation request."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "establishment_id": "b45193cb-a2f1-427f-a4d8-adbb596561b0",
                    "children_count": 30,
                    "meal_type": "lunch",
                }
            ]
        },
    )
    establishment_id: UUID
    children_count: ChildrenCount
    meal_type: MealType


class ReusePreviewInput(BaseModel):
    """Portion count for a read-only rescaled recipe preview."""

    model_config = ConfigDict(extra="forbid")
    children_count: ChildrenCount


class ReuseInput(BaseModel):
    """Client-generated identity and portion count for a reused recipe."""

    model_config = ConfigDict(extra="forbid")
    id: UUID
    children_count: ChildrenCount


class CulturalIdentitiesInput(BaseModel):
    """Replace an establishment's cultural identities."""

    model_config = ConfigDict(extra="forbid")
    identities: list[CulturalIdentity] = Field(max_length=2)


class GramConversionInput(BaseModel):
    """Reviewed mass of one catalog base unit; null removes the conversion."""

    model_config = ConfigDict(extra="forbid")
    grams_per_base_unit: Decimal | None = Field(gt=0, max_digits=12, decimal_places=3)


class RecipeIngredient(BaseModel):
    """Ingredient quantities for the entire meal, in grams and stock units."""

    food_id: UUID
    name: str
    grams: float = Field(gt=0, allow_inf_nan=False)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    unit: MeasurementUnit


class RecipeProposal(BaseModel):
    """An immutable, calculated recipe proposal."""

    id: UUID
    name: str
    portions: int
    ingredients: list[RecipeIngredient]
    steps: list[str]
    indicators: NutritionIndicators
    nutrient_adequacy_percent: dict[str, float]
    macronutrient_percent: dict[str, float]
    gapa_groups: list[str]
    unmet_constraints: list[UnmetConstraint]
    warnings: list[str]
    target_energy_kcal: float
    energy_kcal: float
    cultural_identity: CulturalIdentity | None = None


class RecipeSelectionResponse(BaseModel):
    """A choice and its automatically registered food outflow."""

    model_config = ConfigDict(from_attributes=True)
    proposal_id: UUID
    outflow_id: UUID
    user_id: UUID
    chosen_at: datetime


class RecommendationResponse(BaseModel):
    """A saved request, its proposals and its optional selection."""

    id: UUID
    establishment_id: UUID
    children_count: int
    meal_type: MealType
    user_id: UUID
    created_at: datetime
    prompt_version: str
    proposals: list[RecipeProposal]
    selection: RecipeSelectionResponse | None


class Candidate(BaseModel):
    """One proposed dish and the catalog foods it may use."""

    concept: str = Field(min_length=1, max_length=200)
    food_ids: list[UUID] = Field(min_length=1, max_length=50)
    cultural_identity: CulturalIdentity | None = None


class CandidateBatch(BaseModel):
    """Structured ingredient candidates returned by the model."""

    cultural_dish_viable: bool = Field(
        description="Whether stock supports a dish inspired by a configured identity"
    )
    candidates: list[Candidate] = Field(min_length=2, max_length=3)


class PreparationStep(BaseModel):
    """Preparation instruction with explicit references to its ingredients."""

    text: str = Field(min_length=1, max_length=1500)
    food_ids: list[UUID] = Field(max_length=50)


class RecipeWriting(BaseModel):
    """Model-authored presentation of one calculated recipe."""

    proposal_id: UUID
    name: str = Field(min_length=1, max_length=200)
    steps: list[PreparationStep] = Field(min_length=1, max_length=30)
    cultural_identity: CulturalIdentity | None = None


class WritingBatch(BaseModel):
    """Structured names and steps returned by the model."""

    recipes: list[RecipeWriting] = Field(min_length=2, max_length=3)
