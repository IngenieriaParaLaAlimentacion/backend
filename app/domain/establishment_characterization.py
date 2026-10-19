"""Answer options and status of an establishment's characterization profile.

Every catalog the profile accepts is declared here, so adjusting an option
touches a single place.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class CharacterizationStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class SpaceType(StrEnum):
    COMMUNITY_KITCHEN = "community_kitchen"
    SCHOOL_SUPPORT = "school_support"
    COMMUNITY_HEALTH = "community_health"
    CHILDCARE = "childcare"
    IVE_COUNSELING = "ive_counseling"
    GENDER_VIOLENCE_COUNSELING = "gender_violence_counseling"
    ADDICTION_SUPPORT = "addiction_support"
    HOMELESS_SUPPORT = "homeless_support"
    OLDER_ADULTS_CENTER = "older_adults_center"
    NEIGHBORHOOD_ASSOCIATION = "neighborhood_association"
    ARTS_CULTURE = "arts_culture"
    DISABILITY_CARE = "disability_care"
    FINES = "fines"
    ENVIRONMENTAL = "environmental"
    POPULAR_ECONOMY = "popular_economy"
    SPORTS_CLUB = "sports_club"
    OTHER = "other"


class CareTask(StrEnum):
    FOOD_ASSISTANCE = "food_assistance"
    SCHOOL_SUPPORT = "school_support"
    PRIMARY_HEALTH = "primary_health"
    CHILDCARE = "childcare"
    IVE_COUNSELING = "ive_counseling"
    GENDER_VIOLENCE_SUPPORT = "gender_violence_support"
    ADDICTION_SUPPORT = "addiction_support"
    HOMELESS_SUPPORT = "homeless_support"
    SPORTS = "sports"
    OLDER_ADULTS = "older_adults"
    CULTURAL = "cultural"
    DISABILITY = "disability"
    FINES_TUTORING = "fines_tutoring"
    ENVIRONMENTAL = "environmental"
    POPULAR_ECONOMY = "popular_economy"
    OTHER = "other"


class Premises(StrEnum):
    STREET = "street"
    WORKER_HOME = "worker_home"
    LENT_SPACE = "lent_space"
    RENTED_SPACE = "rented_space"
    OTHER = "other"


class Bathroom(StrEnum):
    EXCLUSIVE = "exclusive"
    SHARED_WITH_HOUSEHOLD = "shared_with_household"
    NONE = "none"
    OTHER = "other"


class Utility(StrEnum):
    RUNNING_WATER = "running_water"
    MOTOR_PUMP_WELL = "motor_pump_well"
    ELECTRICITY = "electricity"
    NATURAL_GAS = "natural_gas"
    GAS_CYLINDER = "gas_cylinder"
    SEWER = "sewer"
    SEPTIC_TANK = "septic_tank"
    INTERNET = "internet"


class Affiliation(StrEnum):
    NGO = "ngo"
    SOCIAL_MOVEMENT = "social_movement"
    LEGAL_STATUS = "legal_status"
    INDEPENDENT = "independent"
    LOCAL_GOVERNMENT = "local_government"
    CHURCH = "church"
    OTHER = "other"


class AttendeeAge(StrEnum):
    EARLY_CHILDHOOD = "early_childhood"
    CHILDREN = "children"
    ADOLESCENTS = "adolescents"
    ADULTS = "adults"
    OLDER_ADULTS = "older_adults"


class Meal(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SNACK = "snack"
    DINNER = "dinner"


class ServiceType(StrEnum):
    ON_SITE = "on_site"
    TAKEAWAY = "takeaway"
    GROCERY_BAG = "grocery_bag"
    OTHER = "other"


class FoodReceptionFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    IRREGULAR = "irregular"


class KitchenEquipment(StrEnum):
    STOVE = "stove"
    OVEN = "oven"
    FRIDGE = "fridge"
    FREEZER = "freezer"
    LARGE_POTS = "large_pots"
    BLENDER = "blender"
    OTHER = "other"


class CulturalIdentity(StrEnum):
    # Provisional catalog, pending validation with community referents.
    INDIGENOUS = "indigenous"
    ANDEAN = "andean"
    GUARANI = "guarani"
    MIGRANT = "migrant"
    CRIOLLO = "criollo"
    OTHER = "other"


def _has_answer(value: Any) -> bool:
    """Return whether a profile value holds an answer."""
    return value not in (None, "", [])


def characterization_status(
    characterization: Mapping[str, Any] | None,
) -> CharacterizationStatus:
    """Return ``complete`` when any profile field holds an answer, else
    ``pending``."""
    if characterization and any(map(_has_answer, characterization.values())):
        return CharacterizationStatus.COMPLETE
    return CharacterizationStatus.PENDING
