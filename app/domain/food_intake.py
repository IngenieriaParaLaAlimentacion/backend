from enum import Enum


class FoodIntakeSource(str, Enum):
    """How a food intake was loaded into the system."""

    MANUAL = "manual"
    PHOTO = "photo"
