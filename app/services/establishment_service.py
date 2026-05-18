from typing import List

from app.models.establishment import Establishment
from app.repositories.establishment_repository import EstablishmentRepository


class EstablishmentService:
    def __init__(self, establishment_repo: EstablishmentRepository):
        self.establishment_repository = establishment_repo

    async def get_all(self) -> List[Establishment]:
        """Return all registered establishments."""
        return await self.establishment_repository.get_all()
