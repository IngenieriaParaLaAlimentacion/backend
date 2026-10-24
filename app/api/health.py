from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_health_service
from app.schemas.health_schema import LivenessResponse, ReadinessResponse
from app.services.health_service import HealthService

router = APIRouter()


@router.get(
    "/health",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description=(
        "Answers 200 while the process is running. Checks no dependency, so it "
        "stays up when the database is down. Public."
    ),
)
async def get_liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Answers 200 when every dependency needed to serve requests responds "
        "within its timeout: currently PostgreSQL. Public."
    ),
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "`/errors/service-not-ready`: a dependency is down; "
            "`checks` names which one"
        },
    },
)
async def get_readiness(
    service: HealthService = Depends(get_health_service),
) -> ReadinessResponse:
    checks = await service.check_readiness()
    return ReadinessResponse(status="ready", checks=checks)
