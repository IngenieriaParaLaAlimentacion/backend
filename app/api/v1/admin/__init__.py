from fastapi import APIRouter

from app.api.v1.admin import (
    establishment_requests,
    field_workers,
    invitations,
    subjects,
    users,
)

router = APIRouter(prefix="/admin")
router.include_router(users.router)
router.include_router(field_workers.router)
router.include_router(invitations.router)
router.include_router(subjects.router)
router.include_router(establishment_requests.router)
