from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.notifications import PushPlatform

InstallationId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
FcmToken = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
DeviceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class DeviceRegistrationRequest(BaseModel):
    """Upsert one app installation for the authenticated user."""

    model_config = ConfigDict(extra="forbid")

    installation_id: InstallationId
    fcm_token: FcmToken
    platform: PushPlatform
    device_name: DeviceName | None = None


class DeviceResponse(BaseModel):
    """Canonical representation of a registered push device."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    installation_id: str
    platform: PushPlatform
    device_name: str | None
