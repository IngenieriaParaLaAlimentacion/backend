from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.establishment import UserEstablishmentStatus
from app.domain.notifications import PushPlatform
from app.domain.user import UserStatus
from app.models.auth.user import User
from app.models.auth.user_establishment import UserEstablishment
from app.models.notifications.user_push_device import UserPushDevice


class UserPushDeviceRepository:
    """Database operations for authenticated push installations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def delete_conflicting_token(
        self, fcm_token: str, installation_id: str
    ) -> None:
        """Delete a token registration owned by a different installation."""
        await self.db.execute(
            delete(UserPushDevice).where(
                UserPushDevice.fcm_token == fcm_token,
                UserPushDevice.installation_id != installation_id,
            )
        )

    async def upsert_installation(
        self,
        *,
        user_id: UUID,
        installation_id: str,
        fcm_token: str,
        platform: PushPlatform,
        device_name: str | None,
    ) -> UserPushDevice:
        """Insert an installation or replace its current owner/token metadata."""
        statement = insert(UserPushDevice).values(
            user_id=user_id,
            installation_id=installation_id,
            fcm_token=fcm_token,
            platform=platform,
            device_name=device_name,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_user_push_devices_installation_id",
            set_={
                "user_id": statement.excluded.user_id,
                "fcm_token": statement.excluded.fcm_token,
                "platform": statement.excluded.platform,
                "device_name": statement.excluded.device_name,
            },
        ).returning(UserPushDevice)
        statement = statement.execution_options(populate_existing=True)
        result = await self.db.execute(statement)
        return result.scalar_one()

    async def delete_for_user_installation(
        self, user_id: UUID, installation_id: str
    ) -> int:
        """Delete only the caller-owned installation and its pending jobs."""
        result = await self.db.execute(
            delete(UserPushDevice).where(
                UserPushDevice.user_id == user_id,
                UserPushDevice.installation_id == installation_id,
            )
        )
        return result.rowcount

    async def delete_if_token_matches(self, *, device_id: UUID, fcm_token: str) -> int:
        """Delete only when the rejected token is still current."""
        result = await self.db.execute(
            delete(UserPushDevice).where(
                UserPushDevice.id == device_id,
                UserPushDevice.fcm_token == fcm_token,
            )
        )
        return result.rowcount

    async def list_eligible_for_establishment(
        self, establishment_id: UUID
    ) -> list[UserPushDevice]:
        """Return all devices of active users with approved access to the
        establishment, whatever their role."""
        result = await self.db.execute(
            select(UserPushDevice)
            .join(User, User.id == UserPushDevice.user_id)
            .join(UserEstablishment, UserEstablishment.user_id == User.id)
            .where(
                UserEstablishment.establishment_id == establishment_id,
                UserEstablishment.status == UserEstablishmentStatus.APPROVED,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(UserPushDevice.id)
        )
        return list(result.scalars().all())
