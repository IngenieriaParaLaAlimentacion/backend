from fastapi import APIRouter

from app.api.v1.router import v1_router
from app.api.v2.router import v2_router

api_router = APIRouter()

api_router.include_router(v1_router)
api_router.include_router(v2_router)
