from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import UserNotFoundError
from app.models.notifications.user_push_device import UserPushDevice
from app.schemas.notifications.device_schema import DeviceRegistrationRequest


class DeviceService:
    """Register and unregister push installations for the current user."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def register(
        self, actor: UserActor, data: DeviceRegistrationRequest
    ) -> UserPushDevice:
        """Upsert an installation and reassign globally duplicated tokens."""
        if await self.uow.user_repo.get_by_id(actor.user_id) is None:
            raise UserNotFoundError(str(actor.user_id))

        await self.uow.push_device_repo.delete_conflicting_token(
            data.fcm_token, data.installation_id
        )
        device = await self.uow.push_device_repo.upsert_installation(
            user_id=actor.user_id,
            installation_id=data.installation_id,
            fcm_token=data.fcm_token,
            platform=data.platform,
            device_name=data.device_name,
        )
        await self.uow.commit()
        return device

    async def unregister(self, actor: UserActor, installation_id: str) -> None:
        """Idempotently remove only the caller's installation."""
        await self.uow.push_device_repo.delete_for_user_installation(
            actor.user_id, installation_id
        )
        await self.uow.commit()
