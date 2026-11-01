from typing import Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    """Liveness probe result."""

    status: Literal["ok"] = Field(description="Always `ok` while the process runs")


class ReadinessResponse(BaseModel):
    """Readiness probe result."""

    status: Literal["ready"] = Field(description="Always `ready` on a 200")
    checks: dict[str, str] = Field(
        description="Outcome of each readiness check, by check name"
    )
