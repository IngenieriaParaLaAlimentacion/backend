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
    CulturalIdentitiesInput,
    CulturalIdentity,
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
    responses=_RESPONSES,
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


@router.get(
    "/cultural-identities",
    response_model=list[CulturalIdentity],
    responses=AUTH_RESPONSES,
)
async def cultural_identity_options(_: UserActor = Depends(require_any)):
    """List the closed set of supported cultural identity codes."""
    return list(CulturalIdentity)


@router.get(
    "/establishments/{establishment_id}/cultural-identities",
    response_model=CulturalIdentitiesInput,
    responses=_RESPONSES,
)
async def establishment_identities(
    establishment_id: UUID,
    actor: UserActor = Depends(require_any),
    service: RecipeService = Depends(get_recipe_service),
):
    """Read identities for an accessible establishment."""
    return await service.identities(establishment_id, actor)


@router.put(
    "/establishments/{establishment_id}/cultural-identities",
    response_model=CulturalIdentitiesInput,
    responses=_RESPONSES,
)
async def replace_identities(
    establishment_id: UUID,
    data: CulturalIdentitiesInput,
    actor: UserActor = Depends(require_admin),
    service: RecipeService = Depends(get_recipe_service),
):
    """Replace an establishment's identities as an administrator."""
    return await service.set_identities(establishment_id, data, actor)


@router.put(
    "/food-catalog/foods/{food_id}/gram-conversion",
    response_model=GramConversionInput,
    responses=_RESPONSES,
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
    responses=_RESPONSES,
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
