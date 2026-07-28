from fastapi import APIRouter

from app.api.v1 import (
    admin,
    analytics,
    auth,
    establishments,
    measurements,
    subjects,
    survey_responses,
    surveys,
    users,
)

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(admin.router, tags=["Admin V1"])
v1_router.include_router(auth.router, tags=["Auth V1"])
v1_router.include_router(establishments.router, tags=["Establishments V1"])
v1_router.include_router(measurements.router, tags=["Measurements V1"])
v1_router.include_router(subjects.router, tags=["Subjects V1"])
v1_router.include_router(surveys.router, tags=["Surveys V1"])
v1_router.include_router(survey_responses.router, tags=["Survey Responses V1"])
v1_router.include_router(users.router, tags=["Users V1"])
v1_router.include_router(analytics.router, tags=["Analytics V1"])
