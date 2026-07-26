from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DashboardIndicatorsResponse(BaseModel):
    """General dashboard indicators (CA4)."""

    model_config = ConfigDict(from_attributes=True)

    response_count: int
    participating_establishments_count: int
    last_event_at: datetime | None
