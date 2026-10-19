import json
import math
import re
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from app.core.interfaces.llm_client import ILlmClient
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import MeasurementUnit
from app.domain.food_outflow import FoodOutflowCategory
from app.domain.nutrition import (
    RecipeRequest,
    RecipeSolution,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    FoodNotFoundError,
    InsufficientStockError,
    LlmClientError,
    RecipeAlreadyChosenError,
    RecipeGenerationError,
    RecipeIdempotencyConflictError,
    RecipeNotFoundError,
    RecipeNoUsableStockError,
    RoleNotAllowedError,
)
from app.models.recipes.recipe import (
    RecipeProposalRecord,
    RecipeRequestRecord,
    RecipeSelection,
)
from app.schemas.food_intakes.food_intake_schema import FoodLineRequest
from app.schemas.food_outflows.food_outflow_schema import FoodOutflowRequest
from app.schemas.pagination import PaginatedResponse
from app.schemas.recipes.recipe_schema import (
    CandidateBatch,
    GramConversionInput,
    RecipeIngredient,
    RecipeProposal,
    RecipeSelectionResponse,
    RecommendationInput,
    RecommendationResponse,
    ReuseInput,
    WritingBatch,
)
from app.services.access import check_establishment_access, check_field_work_access
from app.services.food_outflows.food_outflow_service import FoodOutflowService
from app.services.nutrition.compositions import composition_from_food
from app.services.nutrition.grams import CatalogGramsConverter
from app.services.nutrition.indicators import ENERGY
from app.services.nutrition.nutrition_service import NutritionService
from app.services.recipes.calculations import calculate_proposal, stock_ingredients

PROMPT_VERSION = "v1"
PROMPTS = Path(__file__).parent / "prompts" / PROMPT_VERSION
# Amounts are rendered from the backend snapshot, never from model-authored prose.
_AMOUNT_IN_PROSE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|gr|gramos?|kilogramos?|mg|ml|litros?|lts?|unidades?|tazas?|cucharadas?)\b",
    re.IGNORECASE,
)


class RecipeService:
    """Generate, persist, reuse and choose stock-backed meal recommendations."""

    def __init__(self, uow: IUnitOfWork, llm: ILlmClient | None = None):
        self.uow = uow
        self.llm = llm

    async def _access(self, establishment_id: UUID, actor: UserActor):
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        await check_establishment_access(self.uow, actor, establishment_id)
        await check_field_work_access(self.uow, actor, establishment_id)
        return establishment

    async def _completion(self, template: str, context: dict, schema: type[BaseModel]):
        if self.llm is None:
            raise RecipeGenerationError()
        prompt = (
            (PROMPTS / template)
            .read_text()
            .replace("{context}", json.dumps(context, ensure_ascii=False))
        )
        result = await self.llm.complete(
            prompt=prompt, response_schema=schema.model_json_schema()
        )
        return schema.model_validate(result)

    @staticmethod
    def _response(
        record: RecipeRequestRecord, *, chosen_only: bool = False
    ) -> RecommendationResponse:
        selection = record.selection
        return RecommendationResponse(
            id=record.id,
            establishment_id=record.establishment_id,
            children_count=record.children_count,
            meal_type=record.meal_type,
            user_id=record.user_id,
            created_at=record.created_at,
            prompt_version=record.prompt_version,
            proposals=[
                RecipeProposal.model_validate(p.recipe)
                for p in record.proposals
                if not chosen_only or selection and p.id == selection.proposal_id
            ],
            selection=RecipeSelectionResponse.model_validate(selection)
            if selection
            else None,
        )

    async def _find(
        self,
        request_id: UUID,
        proposal_id: UUID,
        actor: UserActor,
        *,
        lock: bool = False,
    ):
        # Resolve access before acquiring a row lock; check it on every replay too.
        record = await self.uow.recipe_repo.get(request_id)
        if record is None:
            raise RecipeNotFoundError()
        await self._access(record.establishment_id, actor)
        if lock:
            record = await self.uow.recipe_repo.get(request_id, lock=True)
        proposal = next((p for p in record.proposals if p.id == proposal_id), None)
        if proposal is None:
            raise RecipeNotFoundError()
        return record, RecipeProposal.model_validate(proposal.recipe)

    async def generate(
        self, data: RecommendationInput, actor: UserActor
    ) -> RecommendationResponse:
        """Generate two or three complete proposals without reserving stock."""
        establishment = await self._access(data.establishment_id, actor)
        rows = await self.uow.food_stock_repo.stocked_foods(data.establishment_id)
        converter = CatalogGramsConverter([food for food, _ in rows])
        foods = {
            food.id: food
            for food, quantity in rows
            if converter.to_grams(food.id, quantity) is not None
        }
        stock = {food.id: quantity for food, quantity in rows if food.id in foods}
        energy = sum(
            composition_from_food(food).per_100g.get(ENERGY, 0)
            * (converter.to_grams(food.id, stock[food.id]) or 0)
            / 100
            for food in foods.values()
        )
        if energy <= 0:
            raise RecipeNoUsableStockError()
        warnings = (
            [f"{len(rows) - len(foods)} food(s) excluded: no reviewed gram conversion"]
            if len(rows) != len(foods)
            else []
        )
        profile = establishment.characterization or {}
        identities = list(profile.get("cultural_identities") or [])
        identity_other = (
            profile.get("cultural_identities_other") if "other" in identities else None
        )
        recent, _ = await self.uow.recipe_repo.history(
            data.establishment_id, chosen_only=True, limit=10, offset=0
        )
        context = {
            **data.model_dump(mode="json"),
            "cultural_identities": identities,
            "cultural_identities_other": identity_other,
            "stock": [
                {
                    "food_id": str(f.id),
                    "name": f.name,
                    "quantity": str(stock[f.id]),
                    "unit": f.base_unit.value,
                    "gapa_group": composition_from_food(f).gapa_group,
                }
                for f in foods.values()
            ],
            "recent_choices": [
                {
                    "name": p.recipe["name"],
                    "food_ids": [i["food_id"] for i in p.recipe["ingredients"]],
                }
                for r in recent
                for p in r.proposals
                if r.selection and p.id == r.selection.proposal_id
            ],
        }
        nutrition = NutritionService(self.uow, converter)
        proposals = []
        signatures = set()
        failures = []
        try:
            # One initial selection and at most one repair; the writing call is last.
            for _ in range(2):
                try:
                    batch = await self._completion(
                        "select.txt",
                        {
                            **context,
                            "failures": failures,
                            "accepted": [p.model_dump(mode="json") for p in proposals],
                        },
                        CandidateBatch,
                    )
                except ValidationError:
                    failures.append("Candidate response failed schema validation")
                    continue
                for candidate in batch.candidates:
                    if len(proposals) == 3:
                        break
                    ids = sorted(set(candidate.food_ids) & foods.keys())
                    if (
                        not ids
                        or candidate.cultural_identity
                        and candidate.cultural_identity not in identities
                    ):
                        failures.append(
                            "Candidate has no valid foods or its culture is unsupported"
                        )
                        continue
                    solution: RecipeSolution = await nutrition.maximize_recipe(
                        data.establishment_id,
                        RecipeRequest(ids, data.children_count, data.meal_type),
                        actor,
                    )
                    ingredients = stock_ingredients(
                        solution.quantities, foods, converter
                    )
                    if not solution.has_data or not ingredients:
                        failures.append(
                            f"{candidate.concept}: no usable energy after calculation"
                        )
                        continue
                    signature = (
                        frozenset(i.food_id for i in ingredients),
                        candidate.concept.strip().casefold(),
                    )
                    if signature in signatures:
                        failures.append(
                            f"{candidate.concept}: duplicate dish candidate"
                        )
                        continue
                    proposal = calculate_proposal(
                        uuid4(),
                        data.children_count,
                        ingredients,
                        solution.target_energy_kcal,
                        foods,
                        nutrition.profile,
                        warnings + solution.warnings,
                    )
                    if proposal.energy_kcal <= 0:
                        failures.append(
                            f"{candidate.concept}: no energy after rounding"
                        )
                        continue
                    proposal.name = candidate.concept
                    proposal.cultural_identity = candidate.cultural_identity
                    proposals.append(proposal)
                    signatures.add(signature)
                needs_culture = (
                    identities
                    and batch.cultural_dish_viable
                    and not any(p.cultural_identity for p in proposals)
                )
                if needs_culture:
                    failures.append(
                        "Include a culturally inspired candidate when one is viable"
                    )
                    proposals = []
                    signatures = set()
                elif len(proposals) >= 2:
                    break
            if len(proposals) < 2:
                raise RecipeGenerationError()
            written = await self._completion(
                "write.txt",
                {
                    "cultural_identities": identities,
                    "cultural_identities_other": identity_other,
                    "recipes": [p.model_dump(mode="json") for p in proposals],
                },
                WritingBatch,
            )
            if len(written.recipes) != len(proposals) or {
                r.proposal_id for r in written.recipes
            } != {p.id for p in proposals}:
                raise RecipeGenerationError()
            prepared_signatures = set()
            for proposal in proposals:
                presentation = next(
                    r for r in written.recipes if r.proposal_id == proposal.id
                )
                allowed = {i.food_id for i in proposal.ingredients}
                referenced = {
                    fid for step in presentation.steps for fid in step.food_ids
                }
                if (
                    referenced != allowed
                    or any(
                        _AMOUNT_IN_PROSE.search(step.text)
                        for step in presentation.steps
                    )
                    or presentation.cultural_identity != proposal.cultural_identity
                ):
                    raise RecipeGenerationError()
                proposal.name = presentation.name
                proposal.steps = [s.text for s in presentation.steps]
                prepared_signature = (
                    frozenset(i.food_id for i in proposal.ingredients),
                    tuple(step.strip().casefold() for step in proposal.steps),
                )
                if prepared_signature in prepared_signatures:
                    raise RecipeGenerationError()
                prepared_signatures.add(prepared_signature)
        except (LlmClientError, ValidationError) as exc:
            raise RecipeGenerationError() from exc
        request = RecipeRequestRecord(
            id=uuid4(),
            establishment_id=data.establishment_id,
            user_id=actor.user_id,
            children_count=data.children_count,
            meal_type=data.meal_type.value,
            input_snapshot=data.model_dump(mode="json"),
            prompt_version=PROMPT_VERSION,
            proposals=[
                RecipeProposalRecord(
                    id=p.id, position=i, recipe=p.model_dump(mode="json")
                )
                for i, p in enumerate(proposals)
            ],
            selection=None,
        )
        await self.uow.recipe_repo.create(request)
        await self.uow.commit()
        return self._response(request)

    async def history(
        self,
        establishment_id: UUID,
        actor: UserActor,
        *,
        chosen_only: bool,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[RecommendationResponse]:
        """Read recommendation history, optionally restricted to chosen recipes."""
        await self._access(establishment_id, actor)
        records, total = await self.uow.recipe_repo.history(
            establishment_id,
            chosen_only=chosen_only,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return PaginatedResponse(
            items=[self._response(r, chosen_only=chosen_only) for r in records],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size),
        )

    async def _choose(
        self, record: RecipeRequestRecord, proposal: RecipeProposal, actor: UserActor
    ) -> tuple[RecipeSelectionResponse, bool]:
        if record.selection is not None:
            if record.selection.proposal_id != proposal.id:
                raise RecipeAlreadyChosenError()
            return RecipeSelectionResponse.model_validate(record.selection), False
        outflow_id = uuid4()
        await FoodOutflowService(self.uow).register(
            FoodOutflowRequest(
                id=outflow_id,
                establishment_id=record.establishment_id,
                occurred_at=datetime.now(timezone.utc),
                category=FoodOutflowCategory.KITCHEN,
                comments=f"Recipe: {proposal.name}",
                items=[
                    FoodLineRequest(food_id=i.food_id, quantity=i.quantity)
                    for i in proposal.ingredients
                ],
            ),
            actor,
            commit=False,
        )
        selection = RecipeSelection(
            request_id=record.id,
            proposal_id=proposal.id,
            outflow_id=outflow_id,
            user_id=actor.user_id,
        )
        await self.uow.recipe_repo.choose(selection)
        record.selection = selection
        return RecipeSelectionResponse.model_validate(selection), True

    async def choose(
        self, request_id: UUID, proposal_id: UUID, actor: UserActor
    ) -> tuple[RecipeSelectionResponse, bool]:
        """Choose one proposal and deduct stock atomically, with replay protection."""
        record, proposal = await self._find(request_id, proposal_id, actor, lock=True)
        result = await self._choose(record, proposal, actor)
        await self.uow.commit()
        return result

    async def _scale(
        self, original: RecipeRequestRecord, source: RecipeProposal, children_count: int
    ) -> RecipeProposal:
        rows = await self.uow.food_repo.get_with_nutrients_by_ids(
            [i.food_id for i in source.ingredients]
        )
        foods = {food.id: food for food in rows}
        if len(foods) != len(source.ingredients):
            raise RecipeNotFoundError()
        converter = CatalogGramsConverter(rows)
        # Preserve stock-unit quantities when reviewed gram metadata changes.
        ratio = Decimal(children_count) / Decimal(original.children_count)
        ingredients = []
        for item in source.ingredients:
            quantity = (item.quantity * ratio).quantize(
                Decimal("0.001"), rounding=ROUND_DOWN
            )
            if quantity <= 0:
                continue
            if foods[item.food_id].base_unit != item.unit:
                raise RecipeIdempotencyConflictError()
            grams = converter.to_grams(item.food_id, quantity)
            if grams is None:
                raise RecipeNoUsableStockError()
            ingredients.append(
                RecipeIngredient(
                    food_id=item.food_id,
                    name=item.name,
                    quantity=quantity,
                    grams=grams,
                    unit=item.unit,
                )
            )
        if len(ingredients) != len(source.ingredients):
            raise RecipeNoUsableStockError()
        nutrition = NutritionService(self.uow, converter)
        target = (
            children_count
            * nutrition.profile.energy_kcal
            * nutrition.profile.meal_energy_fractions[original.meal_type]
        )
        proposal = calculate_proposal(
            uuid4(),
            children_count,
            ingredients,
            target,
            foods,
            nutrition.profile,
            source.warnings,
        )
        if proposal.energy_kcal <= 0:
            raise RecipeNoUsableStockError()
        proposal.name, proposal.steps, proposal.cultural_identity = (
            source.name,
            source.steps,
            source.cultural_identity,
        )
        return proposal

    async def preview_reuse(
        self, request_id: UUID, proposal_id: UUID, children_count: int, actor: UserActor
    ) -> RecipeProposal:
        """Preview rescaled quantities and current stock without writing any records."""
        original, source = await self._find(request_id, proposal_id, actor)
        proposal = await self._scale(original, source, children_count)
        balances = await self.uow.food_stock_repo.get_many(
            original.establishment_id, [i.food_id for i in proposal.ingredients]
        )
        for item in proposal.ingredients:
            available = balances.get(item.food_id, Decimal(0))
            if item.quantity > available:
                raise InsufficientStockError(
                    food_id=str(item.food_id),
                    requested=str(item.quantity),
                    available=str(available),
                )
        return proposal

    async def reuse(
        self, request_id: UUID, proposal_id: UUID, data: ReuseInput, actor: UserActor
    ) -> tuple[RecommendationResponse, bool]:
        """Scale and choose a saved recipe without a model call; replay by client id."""
        original, source = await self._find(request_id, proposal_id, actor)
        snapshot = {
            "source_request_id": str(request_id),
            "source_proposal_id": str(proposal_id),
            "children_count": data.children_count,
        }
        await self.uow.recipe_repo.lock_reuse_id(data.id)
        existing = await self.uow.recipe_repo.get(data.id)
        if existing:
            if (
                existing.establishment_id != original.establishment_id
                or existing.input_snapshot != snapshot
            ):
                raise RecipeIdempotencyConflictError()
            return self._response(existing), False
        proposal = await self._scale(original, source, data.children_count)
        record = RecipeRequestRecord(
            id=data.id,
            establishment_id=original.establishment_id,
            user_id=actor.user_id,
            children_count=data.children_count,
            meal_type=original.meal_type,
            input_snapshot=snapshot,
            prompt_version=original.prompt_version,
            proposals=[
                RecipeProposalRecord(
                    id=proposal.id, position=0, recipe=proposal.model_dump(mode="json")
                )
            ],
            selection=None,
        )
        await self.uow.recipe_repo.create(record)
        await self._choose(record, proposal, actor)
        await self.uow.commit()
        return self._response(record), True

    async def set_conversion(
        self, food_id: UUID, data: GramConversionInput, actor: UserActor
    ) -> GramConversionInput:
        """Configure a reviewed stock-unit mass as an administrator."""
        if actor.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            raise RoleNotAllowedError()
        foods = await self.uow.food_repo.get_by_ids([food_id])
        if not foods:
            raise FoodNotFoundError(str(food_id))
        food = foods[0]
        value = (
            Decimal(1000)
            if food.base_unit == MeasurementUnit.KILOGRAMOS
            else data.grams_per_base_unit
        )
        await self.uow.food_repo.set_gram_conversion(food, value)
        await self.uow.commit()
        return GramConversionInput(grams_per_base_unit=value)
