"""Bounded recipe model workflow over plain snapshots; no database operations."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, TypeVar
from uuid import UUID, uuid4

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from app.core.interfaces.llm_client import ILlmClient
from app.domain.food_catalog import MeasurementUnit
from app.domain.nutrition import FoodComposition, RecipeRequest, StockedFood
from app.exceptions.domain_exceptions import LlmClientError, RecipeGenerationError
from app.schemas.recipes.recipe_schema import (
    CandidateBatch,
    RecipeProposal,
    RecommendationInput,
    WritingBatch,
)
from app.services.nutrition.grams import CatalogGramsConverter
from app.services.nutrition.nutrition_service import NutritionService
from app.services.recipes.calculations import calculate_proposal, stock_ingredients

ResponseT = TypeVar("ResponseT", bound=BaseModel)

logger = structlog.get_logger()
PROMPT_VERSION = "v1"
PROMPTS = Path(__file__).parent / "prompts" / PROMPT_VERSION
# Quantities in Spanish, including fractions and compound number words. Time
# and temperature units deliberately do not appear in the ingredient-unit list.
_NUMBER_WORD = (
    r"(?:un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|"
    r"trece|catorce|quince|diecis[eé]is|diecisiete|dieciocho|diecinueve|veinte|"
    r"veinti(?:un[ao]?|ún|d[oó]s|tr[eé]s|cuatro|cinco|s[eé]is|siete|ocho|nueve)|"
    r"treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa|cien(?:to)?|"
    r"doscientos|trescientos|cuatrocientos|quinientos|seiscientos|setecientos|"
    r"ochocientos|novecientos|mil|medi[oa]s?|cuartos?)"
)
_AMOUNT_IN_PROSE = re.compile(
    r"(?<!\w)(?:\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?|[½¼¾⅓⅔]|"
    + _NUMBER_WORD
    + r"(?:\s+(?:y\s+)?"
    + _NUMBER_WORD
    + r")*)"
    r"(?:\s+de)?\s*"
    r"(?:kg|g|grs?|gramos?|kilogramos?|kilos?|mg|ml|cl|cc|l|litros?|lts?|"
    r"unidad(?:es)?|tazas?|cucharadas?|cucharaditas?|cdas?|cditas?|vasos?|latas?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FoodSnapshot:
    id: UUID
    name: str
    base_unit: MeasurementUnit


@dataclass
class GenerationSnapshot:
    context: dict
    foods: dict[UUID, FoodSnapshot]
    compositions: dict[UUID, FoodComposition]
    stocked: list[StockedFood]
    converter: CatalogGramsConverter
    warnings: list[str]

    @property
    def identities(self) -> list[str]:
        return self.context["cultural_identities"]


def writing_response_schema() -> dict:
    """Keep the wire schema small; enforce all bounds with WritingBatch locally.

    Large bounds on nested arrays can exceed provider structured-output
    complexity limits. Do not encode text lengths, UUID formats or array
    cardinalities in the decoder; validation below still rejects invalid output.
    """
    omitted = {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "format",
        "title",
        "default",
    }

    def simplify(value):
        if isinstance(value, dict):
            return {
                key: simplify(item) for key, item in value.items() if key not in omitted
            }
        if isinstance(value, list):
            return [simplify(item) for item in value]
        return value

    return simplify(WritingBatch.model_json_schema())


class RecipeGenerator:
    def __init__(self, llm: ILlmClient | None, nutrition: NutritionService):
        self.llm = llm
        self.nutrition = nutrition

    @staticmethod
    def _fail(stage: str, reason: str, failures: list[str] | None = None) -> NoReturn:
        # Only controlled reason codes are logged; never prompts, stock or model text.
        logger.warning(
            "recipes.generation_failed",
            stage=stage,
            reason=reason,
            prompt_version=PROMPT_VERSION,
            failures=failures or [],
        )
        raise RecipeGenerationError()

    async def _completion(
        self, stage: str, template: str, context: dict, schema: type[ResponseT]
    ) -> ResponseT:
        if self.llm is None:
            self._fail(stage, "client_unavailable")
        prompt = (
            (PROMPTS / template)
            .read_text()
            .replace("{context}", json.dumps(context, ensure_ascii=False))
        )
        try:
            result = await self.llm.complete(
                prompt=prompt,
                response_schema=writing_response_schema()
                if schema is WritingBatch
                else schema.model_json_schema(),
            )
            return schema.model_validate(result)
        except LlmClientError as exc:
            cause = exc
            timeout = False
            for _ in range(5):
                timeout = timeout or isinstance(
                    cause, (TimeoutError, httpx.TimeoutException)
                )
                cause = cause.__cause__ or cause.__context__
                if cause is None:
                    break
            self._fail(
                stage,
                "provider_timeout" if timeout else "provider_failure",
                context.get("failures"),
            )

    async def generate(
        self, data: RecommendationInput, snapshot: GenerationSnapshot
    ) -> list[RecipeProposal]:
        proposals = await self._select(data, snapshot)
        try:
            return await self._write(proposals, snapshot)
        except ValidationError:
            self._fail("writing", "schema_validation")

    async def _select(
        self, data: RecommendationInput, snapshot: GenerationSnapshot
    ) -> list[RecipeProposal]:
        proposals = []
        signatures = set()
        failures = []
        # One initial selection and at most one repair; the writing call is last.
        for attempt in range(2):
            try:
                batch = await self._completion(
                    "selection",
                    "select.txt",
                    {
                        **snapshot.context,
                        "failures": failures,
                        "accepted": [p.model_dump(mode="json") for p in proposals],
                    },
                    CandidateBatch,
                )
            except ValidationError:
                failures.append("candidate_schema_validation")
                continue
            for candidate in batch.candidates:
                if len(proposals) == 3:
                    break
                supplied_ids = set(candidate.food_ids)
                if supplied_ids - snapshot.foods.keys():
                    failures.append("food_ids_outside_stock")
                ids = sorted(supplied_ids & snapshot.foods.keys())
                if (
                    not ids
                    or candidate.cultural_identity
                    and candidate.cultural_identity not in snapshot.identities
                ):
                    failures.append("invalid_foods_or_unconfigured_culture")
                    continue
                solution = await self.nutrition.maximize_stocked_recipe(
                    RecipeRequest(ids, data.children_count, data.meal_type),
                    snapshot.stocked,
                )
                ingredients = stock_ingredients(
                    solution.quantities, snapshot.foods, snapshot.converter
                )
                if not solution.has_data or not ingredients:
                    failures.append("no_usable_energy")
                    continue
                signature = (
                    frozenset(i.food_id for i in ingredients),
                    candidate.concept.strip().casefold(),
                )
                if signature in signatures:
                    failures.append("duplicate_candidate")
                    continue
                proposal = calculate_proposal(
                    uuid4(),
                    data.children_count,
                    ingredients,
                    solution.target_energy_kcal,
                    snapshot.foods,
                    self.nutrition.profile,
                    snapshot.warnings + solution.warnings,
                    compositions=snapshot.compositions,
                )
                if proposal.energy_kcal <= 0:
                    failures.append("no_energy_after_rounding")
                    continue
                proposal.name = candidate.concept
                proposal.cultural_identity = candidate.cultural_identity
                proposals.append(proposal)
                signatures.add(signature)
            needs_culture = (
                snapshot.identities
                and batch.cultural_dish_viable
                and not any(p.cultural_identity for p in proposals)
            )
            if needs_culture:
                failures.append("missing_viable_cultural_dish")
                proposals = []
                signatures = set()
            elif len(proposals) >= 2:
                break
            logger.warning(
                "recipes.candidates_rejected",
                stage="selection",
                reason="repair_needed",
                prompt_version=PROMPT_VERSION,
                failures=list(failures),
                attempt=attempt + 1,
            )
        if len(proposals) < 2:
            self._fail("selection", "insufficient_valid_proposals", failures)
        return proposals

    async def _write(
        self, proposals: list[RecipeProposal], snapshot: GenerationSnapshot
    ) -> list[RecipeProposal]:
        written = await self._completion(
            "writing",
            "write.txt",
            {
                "cultural_identities": snapshot.identities,
                "cultural_identities_other": snapshot.context[
                    "cultural_identities_other"
                ],
                "recipes": [p.model_dump(mode="json") for p in proposals],
            },
            WritingBatch,
        )
        if len(written.recipes) != len(proposals) or {
            r.proposal_id for r in written.recipes
        } != {p.id for p in proposals}:
            self._fail("writing", "proposal_ids_mismatch")
        prepared_signatures = set()
        for proposal in proposals:
            presentation = next(
                r for r in written.recipes if r.proposal_id == proposal.id
            )
            allowed = {i.food_id for i in proposal.ingredients}
            referenced = {fid for step in presentation.steps for fid in step.food_ids}
            if referenced != allowed:
                self._fail("writing", "ingredient_references_mismatch")
            if any(_AMOUNT_IN_PROSE.search(step.text) for step in presentation.steps):
                self._fail("writing", "quantities_in_prose")
            if presentation.cultural_identity != proposal.cultural_identity:
                self._fail("writing", "culture_mismatch")
            proposal.name = presentation.name
            proposal.steps = [s.text for s in presentation.steps]
            prepared_signature = (
                frozenset(i.food_id for i in proposal.ingredients),
                tuple(step.strip().casefold() for step in proposal.steps),
            )
            if prepared_signature in prepared_signatures:
                self._fail("writing", "duplicate_preparation")
            prepared_signatures.add(prepared_signature)
        return proposals
