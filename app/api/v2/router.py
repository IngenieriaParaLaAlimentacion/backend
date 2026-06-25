from fastapi import APIRouter

from app.api.v2 import admin, auth

v2_router = APIRouter(prefix="/api/v2")

v2_router.include_router(admin.router, tags=["Admin V2"])
v2_router.include_router(auth.router, tags=["Auth V2"])
