from fastapi import APIRouter

from app.api.v1.internal import stale_establishment_notifications

router = APIRouter(prefix="/internal")
router.include_router(stale_establishment_notifications.router)
