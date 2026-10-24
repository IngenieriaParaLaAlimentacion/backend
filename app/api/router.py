from fastapi import APIRouter

from app.api import health
from app.api.v1.router import v1_router

api_router = APIRouter()

# Operational probes stay outside the versioned business API.
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(v1_router)
