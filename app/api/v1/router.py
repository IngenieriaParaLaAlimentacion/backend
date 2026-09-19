from fastapi import APIRouter

from app.api.v1 import (
    admin,
    analytics,
    auth,
    establishments,
    food_intakes,
    food_outflows,
    internal,
    measurements,
    subjects,
    users,
)
from app.api.v1.food_catalog import categories as food_catalog_categories
from app.api.v1.food_catalog import foods as food_catalog_foods
from app.api.v1.surveys import responses as survey_responses
from app.api.v1.surveys import surveys

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(admin.router, tags=["Admin V1"])
v1_router.include_router(auth.router, tags=["Auth V1"])
v1_router.include_router(establishments.router, tags=["Establishments V1"])
v1_router.include_router(food_catalog_categories.router, tags=["Food Catalog V1"])
v1_router.include_router(food_catalog_foods.router, tags=["Food Catalog V1"])
v1_router.include_router(food_intakes.router, tags=["Food Intakes V1"])
v1_router.include_router(food_outflows.router, tags=["Food Outflows V1"])
v1_router.include_router(measurements.router, tags=["Measurements V1"])
v1_router.include_router(subjects.router, tags=["Subjects V1"])
v1_router.include_router(surveys.router, tags=["Surveys V1"])
v1_router.include_router(survey_responses.router, tags=["Survey Responses V1"])
v1_router.include_router(users.router, tags=["Users V1"])
v1_router.include_router(analytics.router, tags=["Analytics V1"])
v1_router.include_router(internal.router, tags=["Internal V1"])
