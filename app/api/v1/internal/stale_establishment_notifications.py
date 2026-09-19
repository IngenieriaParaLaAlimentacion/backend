from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import (
    get_stale_establishment_notification_service,
    require_internal_cron,
)
from app.services.notifications.stale_establishment_notification_service import (
    StaleEstablishmentNotificationService,
)

router = APIRouter(prefix="/stale-establishment-notifications")


@router.post(
    "/run",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Process stale-establishment notifications",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid internal secret"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Notification integration is not configured"
        },
    },
    dependencies=[Depends(require_internal_cron)],
)
async def run_stale_establishment_notifications(
    service: StaleEstablishmentNotificationService = Depends(
        get_stale_establishment_notification_service
    ),
) -> Response:
    await service.run()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
