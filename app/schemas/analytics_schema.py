from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SurveyResponseSummaryResponse(BaseModel):
    """Aggregated metrics over survey responses."""

    model_config = ConfigDict(from_attributes=True)

    response_count: int = Field(
        description="Total survey responses matching the applied filters"
    )
    participating_establishments_count: int = Field(
        description="Distinct establishments that submitted at least one response"
    )
    last_event_at: datetime | None = Field(
        description="Timestamp of the most recent survey response (null if none match)"
    )
