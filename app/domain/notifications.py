from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PushPlatform(StrEnum):
    """Mobile platforms supported by the push registration contract."""

    ANDROID = "android"
    IOS = "ios"


@dataclass(frozen=True)
class EstablishmentOutflowActivity:
    """Latest event-time outflow for an establishment requiring cycle sync."""

    establishment_id: UUID
    last_outflow_at: datetime


@dataclass(frozen=True)
class PushDeliveryContext:
    """Current target and payload identifiers for one claimed job."""

    job_id: UUID
    device_id: UUID
    fcm_token: str
    platform: PushPlatform
    establishment_id: UUID
    establishment_name: str
    threshold_hours: int
    attempt_count: int
