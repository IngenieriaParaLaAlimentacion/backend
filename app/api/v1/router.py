from fastapi import APIRouter

from app.api.v1 import admin, auth, establishments, subjects, users

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(admin.router, tags=["Admin V1"])
v1_router.include_router(auth.router, tags=["Auth V1"])
v1_router.include_router(establishments.router, tags=["Establishments V1"])
v1_router.include_router(subjects.router, tags=["Subjects V1"])
v1_router.include_router(users.router, tags=["Users V1"])
