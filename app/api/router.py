from fastapi import APIRouter

from app.api.v0.router import v0_router
from app.api.v1.router import v1_router

api_router = APIRouter()

api_router.include_router(v0_router)
api_router.include_router(v1_router)
