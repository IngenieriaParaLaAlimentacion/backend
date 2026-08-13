from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

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

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
