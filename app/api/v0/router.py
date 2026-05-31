from fastapi import APIRouter

from app.api.v1 import admin, auth, establishments, subjects

v0_router = APIRouter(prefix="/api")

v0_router.include_router(admin.router, tags=["Admin"])
v0_router.include_router(auth.router, tags=["Auth"])
v0_router.include_router(establishments.router, tags=["Establishments"])
v0_router.include_router(subjects.router, tags=["Subjects"])
