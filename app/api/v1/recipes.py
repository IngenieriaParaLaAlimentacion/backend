from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import (
    get_recipe_generation_service,
    get_recipe_service,
    require_admin,
    require_any,
)
from app.domain.user import UserActor
from app.schemas.pagination import PaginatedResponse
from app.schemas.recipes.recipe_schema import (
    GramConversionInput,
    RecipeProposal,
    RecipeSelectionResponse,
    RecommendationInput,
    RecommendationResponse,
    ReuseInput,
    ReusePreviewInput,
)
from app.services.recipes.recipe_service import RecipeService

router = APIRouter()
_RESPONSES = {
    **AUTH_RESPONSES,
    404: {"description": "Establishment, request, proposal or food not found"},
    409: {"description": "No usable stock, insufficient stock, or conflicting choice"},
    422: {"description": "Invalid input"},
}


@router.post(
    "/recipe-recommendations",
    response_model=RecommendationResponse,
    status_code=201,
    responses={
        **_RESPONSES,
        502: {"description": "Model failed or returned invalid proposals"},
    },
    summary="Generate 2–3 stock-backed recipe proposals",
    description=(
        "Generate and save proposals for the establishment, children count and meal "
        "type using current stock, the establishment characterization and recent "
        "choices. Requires establishment access and, for analysts, a subscription. "
        "Quantities come from the nutrition optimizer; energy and nutritional "
        "shortfalls are returned explicitly. Generation does not deduct stock."
    ),
)
async def generate_recommendations(
    data: RecommendationInput,
    actor: UserActor = Depends(require_any),
    service: RecipeService = Depends(get_recipe_generation_service),
):
    """Generate recipes with explicit nutritional and energy shortfalls."""
    return await service.generate(data, actor)


@router.get(
    "/establishments/{establishment_id}/recipe-recommendations",
    response_model=PaginatedResponse[RecommendationResponse],
    status_code=200,
    responses=_RESPONSES,
    summary="List an establishment's recipe recommendation history",
    description=(
        "Return saved requests, newest first, with standard page and page_size "
        "pagination. With chosen_only=true, exclude unchosen requests and return "
        "only the chosen proposal in each request. Requires establishment access "
        "and, for analysts, a subscription. No model call or stock deduction occurs."
    ),
)
async def recommendation_history(
    establishment_id: UUID,
    chosen_only: bool = False,
    pagination: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(require_any),
    service: RecipeService = Depends(get_recipe_service),
):
    """List requests and optionally only their chosen proposals."""
    return await service.history(
        establishment_id,
        actor,
        chosen_only=chosen_only,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "/recipe-recommendations/{request_id}/proposals/{proposal_id}/choose",
    response_model=RecipeSelectionResponse,
    status_code=201,
    responses={**_RESPONSES, 200: {"description": "Idempotent replay"}},
    summary="Choose a recipe and deduct its ingredients",
    description=(
        "Atomically choose one proposal and create its kitchen food outflow. "
        "Current stock is checked at confirmation; a shortage rolls back the "
        "whole operation. Repeating the same choice returns 200 without another "
        "deduction; choosing a different proposal for that request returns 409. "
        "Requires establishment access and, for analysts, a subscription."
    ),
)
async def choose_recipe(
    request_id: UUID,
    proposal_id: UUID,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: RecipeService = Depends(get_recipe_service),
):
    """Choose a proposal and deduct its ingredients in one transaction."""
    result, created = await service.choose(request_id, proposal_id, actor)
    if not created:
        response.status_code = 200
    return result


@router.post(
    "/recipe-recommendations/{request_id}/proposals/{proposal_id}/reuse",
    response_model=RecommendationResponse,
    status_code=201,
    responses={**_RESPONSES, 200: {"description": "Idempotent reuse replay"}},
    summary="Scale and choose a saved recipe without a model call",
    description=(
        "Create a scaled copy for children_count and atomically deduct its "
        "ingredients. The original stays unchanged. Retry with the same client "
        "UUID, source and count to receive 200 without another deduction; changing "
        "the meaning of that UUID returns 409. Current stock and establishment "
        "access, including analyst subscription, are checked on confirmation."
    ),
)
async def reuse_recipe(
    request_id: UUID,
    proposal_id: UUID,
    data: ReuseInput,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: RecipeService = Depends(get_recipe_service),
):
    """Scale and choose a previous recipe without invoking a model."""
    result, created = await service.reuse(request_id, proposal_id, data, actor)
    if not created:
        response.status_code = 200
    return result


@router.put(
    "/food-catalog/foods/{food_id}/gram-conversion",
    response_model=GramConversionInput,
    status_code=200,
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Food not found"},
        422: {"description": "Invalid gram conversion"},
    },
    summary="Set a reviewed food mass conversion",
    description=(
        "Admins and superadmins may set grams_per_base_unit for one litre or "
        "one unit of a catalog food; null removes that factor. Kilograms always "
        "use 1000 grams. This is a temporary catalog adapter pending the shared "
        "conversion module and food equivalences in backend issue #192. Once "
        "integrated, the shared module and equivalence management replace this "
        "adapter and endpoint. Missing factors are never estimated."
    ),
)
async def set_gram_conversion(
    food_id: UUID,
    data: GramConversionInput,
    actor: UserActor = Depends(require_admin),
    service: RecipeService = Depends(get_recipe_service),
):
    """Set the reviewed mass of a food's stock unit as an administrator."""
    return await service.set_conversion(food_id, data, actor)


@router.post(
    "/recipe-recommendations/{request_id}/proposals/{proposal_id}/reuse-preview",
    response_model=RecipeProposal,
    status_code=200,
    responses=_RESPONSES,
    summary="Preview a saved recipe for a different number of children",
    description=(
        "Scale recorded ingredient quantities and recalculate nutritional "
        "indicators for children_count without a model call, saving a request "
        "or deducting stock. Check current stock and establishment access, "
        "including analyst subscription. Stock is checked again when reuse is "
        "confirmed; a successful preview does not reserve ingredients."
    ),
)
async def preview_recipe_reuse(
    request_id: UUID,
    proposal_id: UUID,
    data: ReusePreviewInput,
    actor: UserActor = Depends(require_any),
    service: RecipeService = Depends(get_recipe_service),
):
    """Preview rescaled quantities before confirming a stock deduction."""
    return await service.preview_reuse(
        request_id, proposal_id, data.children_count, actor
    )
