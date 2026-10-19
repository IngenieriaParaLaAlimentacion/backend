from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthRepository:
    """Probes the database connection for readiness checks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ping(self) -> None:
        """Run a trivial query, raising if the database cannot answer it."""
        await self.session.execute(text("SELECT 1"))
