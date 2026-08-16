from sqlalchemy.ext.asyncio import AsyncSession

from app.models.establishments.establishment_request import (
    EstablishmentRequest,
)


class EstablishmentRequestRepository:
    """Persistence operations for establishment creation requests."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, request: EstablishmentRequest) -> EstablishmentRequest:
        """Persist a new establishment creation request."""
        self.db.add(request)
        await self.db.flush()
        await self.db.refresh(request)
        return request
