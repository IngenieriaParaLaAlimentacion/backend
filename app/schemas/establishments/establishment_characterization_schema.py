from typing import Annotated, Any, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    EmailStr,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.domain.establishment_characterization import (
    Affiliation,
    AttendeeAge,
    Bathroom,
    CareTask,
    CulturalIdentity,
    FoodReceptionFrequency,
    KitchenEquipment,
    Meal,
    Premises,
    ServiceType,
    SpaceType,
    Utility,
    Weekday,
)

T = TypeVar("T")

_OTHER = "other"
_OTHER_SUFFIX = "_other"


def _blank_to_none(value: Any) -> Any:
    """Read a blank string as an unanswered field."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _none_to_empty_list(value: Any) -> Any:
    """Read a null list as an unanswered field."""
    return [] if value is None else value


def _reject_duplicates(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("Values must not repeat.")
    return values


OptionalText = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None,
    BeforeValidator(_blank_to_none),
]
OptionalPhone = Annotated[
    Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, max_length=30, pattern=r"^[0-9+\-\s()]+$"
        ),
    ]
    | None,
    BeforeValidator(_blank_to_none),
]
OptionalEmail = Annotated[EmailStr | None, BeforeValidator(_blank_to_none)]
UniqueList = Annotated[
    list[T],
    BeforeValidator(_none_to_empty_list),
    AfterValidator(_reject_duplicates),
]
LocalTime = Annotated[
    str,
    Field(
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="Local time of the establishment, 24 h `HH:MM`.",
        examples=["11:30"],
    ),
]


class OpeningHoursSlot(BaseModel):
    """Days of the week sharing the same opening and closing time."""

    days: UniqueList[Weekday] = Field(min_length=1)
    opens_at: LocalTime
    closes_at: LocalTime

    @model_validator(mode="after")
    def closes_after_opening(self) -> "OpeningHoursSlot":
        # Zero-padded HH:MM strings sort the same as the times they hold.
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be later than opens_at.")
        return self


class EstablishmentCharacterization(BaseModel):
    """Profile of an establishment. Every field is optional: ``null`` or
    ``[]`` means unanswered. Each ``*_other`` text is accepted only when
    ``"other"`` is chosen in the field it belongs to."""

    district: OptionalText = None
    neighborhood: OptionalText = None
    cross_streets: OptionalText = None
    contact_phone: OptionalPhone = Field(
        default=None,
        description="Private contact data: never exposed on public endpoints.",
    )
    contact_email: OptionalEmail = None
    opening_hours: Annotated[
        list[OpeningHoursSlot], BeforeValidator(_none_to_empty_list)
    ] = []

    space_types: UniqueList[SpaceType] = []
    space_types_other: OptionalText = None
    care_tasks: UniqueList[CareTask] = []
    care_tasks_other: OptionalText = None
    premises: Premises | None = None
    premises_other: OptionalText = None
    bathroom: Bathroom | None = None
    bathroom_other: OptionalText = None
    utilities: UniqueList[Utility] = []
    affiliations: UniqueList[Affiliation] = []
    affiliations_other: OptionalText = None

    daily_attendance: int | None = Field(
        default=None,
        ge=0,
        le=100_000,
        description="People attended in total on a normal day.",
    )
    attendee_ages: UniqueList[AttendeeAge] = []

    meals: UniqueList[Meal] = []
    service_types: UniqueList[ServiceType] = []
    service_types_other: OptionalText = None
    food_reception_frequency: FoodReceptionFrequency | None = None
    cooks_per_service: int | None = Field(
        default=None,
        ge=0,
        le=1_000,
        description="People cooking in a normal service.",
    )
    kitchen_equipment: UniqueList[KitchenEquipment] = []
    kitchen_equipment_other: OptionalText = None

    cultural_identities: UniqueList[CulturalIdentity] = []
    cultural_identities_other: OptionalText = None

    @field_validator(
        "space_types_other",
        "care_tasks_other",
        "premises_other",
        "bathroom_other",
        "affiliations_other",
        "service_types_other",
        "kitchen_equipment_other",
        "cultural_identities_other",
    )
    @classmethod
    def other_text_requires_other(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        # Validated per field, not on the model, so the error names this field.
        if value is None:
            return value
        chosen = info.data.get(info.field_name.removesuffix(_OTHER_SUFFIX))
        is_other_chosen = (
            _OTHER in chosen if isinstance(chosen, list) else chosen == _OTHER
        )
        if not is_other_chosen:
            raise ValueError('Only accepted when "other" is chosen.')
        return value
