from fastapi import APIRouter

from app.api.v1.admin import field_workers, invitations, subjects, users

router = APIRouter(prefix="/admin")
router.include_router(users.router)
router.include_router(field_workers.router)
router.include_router(invitations.router)
router.include_router(subjects.router)
