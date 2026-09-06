from fastapi import APIRouter

from app.api.v1.establishments import catalog, dashboard

router = APIRouter()
router.include_router(catalog.router)
router.include_router(dashboard.router)
