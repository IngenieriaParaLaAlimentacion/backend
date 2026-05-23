import logging

from app.core.config import settings
from app.core.security import hash_password
from app.db.unit_of_work import UnitOfWork
from app.domain.user import UserRole, UserStatus
import asyncio



logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

async def create_super_admin() -> None:
    async with UnitOfWork() as uow:
        try:
            if await uow.user_repo.get_by_email(settings.seed_admin_email):
                logger.error("Super admin already exists")
                return

            logger.info("Creating super admin")
            new_admin = await uow.user_repo.create(
                email=settings.seed_admin_email,
                name="Super",
                last_name="Admin",
                role=UserRole.SUPERADMIN,
                status=UserStatus.ACTIVE,
            )

            await uow.password_repo.create(
                user_id=new_admin.id,
                password_hashed=hash_password(settings.seed_admin_password),
            )
            await uow.commit()
            logger.info(f"Super admin created: {settings.seed_admin_email}")

        except Exception as error:
            logger.error(f"Error creating super admin: {error}")
            raise


if __name__ == "__main__":
    asyncio.run(create_super_admin())
