from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, Field, PlainSerializer, StringConstraints

ValidStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]
DescriptionStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500),
]
PhoneStr = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=20,
        pattern=r"^[0-9+\-\s()]+$",
    ),
]


def _min_password_length(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    return v


PasswordStr = Annotated[str, AfterValidator(_min_password_length)]

ClientGeneratedId = Annotated[
    UUID | None,
    Field(
        default=None,
        description=(
            "Client-generated UUID for offline-first idempotency. When provided it "
            "becomes the resource's primary key and repeated submissions with the "
            "same id are idempotent. When omitted, the server generates one."
        ),
    ),
]


def _round_to_2(v: float | None) -> float | None:
    """Round to two decimals for serialization, passing None through."""
    return None if v is None else round(v, 2)


# Floats keep full precision in storage and alert computation; they are rounded
# to two decimals only when serialized for API responses.
RoundedNullableFloat = Annotated[
    float | None,
    PlainSerializer(_round_to_2, return_type=float | None),
]

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
