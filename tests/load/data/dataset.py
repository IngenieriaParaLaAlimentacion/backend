"""Fictitious dataset the load tests run against.

It is generated rather than listed: each establishment gets one field worker and the
same number of subjects, so the volume is set by the constants below. Every person
and organisation here is made up. ``tests/load/data/seed.py`` loads it.
"""

import uuid

from app.domain.subject import Sex
from app.domain.user import UserRole
from app.reference_data.reference_e2e_dataset import (
    Reading,
    ReferenceEstablishment,
    ReferenceSubject,
    ReferenceUser,
)

ESTABLISHMENT_COUNT = 10
SUBJECTS_PER_ESTABLISHMENT = 200
READINGS_PER_SUBJECT = 3

# Every seeded record carries it in a text field, as do the records the load tests
# write, so they can be found and removed straight from the database.
MARKER = "LOADTEST"

FIES_SURVEY_NAME = f"{MARKER} Encuesta FIES"

# Kept apart from the reference dataset's DNIs, which start at 90_000_001.
_FIRST_DNI = 80_000_001

# Fixed, so the same key always gives the same id and a second run finds its rows.
_NAMESPACE = uuid.UUID("5c3b6a0e-2f4d-4e8a-9b7c-1d2e3f4a5b6c")

_NAMES = (
    ("Lucía", Sex.FEMALE),
    ("Martina", Sex.FEMALE),
    ("Sofía", Sex.FEMALE),
    ("Camila", Sex.FEMALE),
    ("Julieta", Sex.FEMALE),
    ("Benjamín", Sex.MALE),
    ("Tomás", Sex.MALE),
    ("Joaquín", Sex.MALE),
    ("Santiago", Sex.MALE),
    ("Lautaro", Sex.MALE),
)
_LAST_NAMES = ("Gómez", "Pérez", "Díaz", "Romero", "Sosa")


def load_test_id(*parts: str) -> uuid.UUID:
    """Return the id the dataset gives to the record named by ``parts``."""
    return uuid.uuid5(_NAMESPACE, "/".join(parts))


def _establishment_key(number: int) -> str:
    return f"loadtest_{number:02d}"


def _establishments() -> tuple[ReferenceEstablishment, ...]:
    # Spread along a line through Buenos Aires, so every one has its own place.
    return tuple(
        ReferenceEstablishment(
            key=_establishment_key(number),
            name=f"{MARKER} Comedor {number:02d}",
            formatted_address=f"{MARKER} Comedor {number:02d}, Buenos Aires, Argentina",
            city="Ciudad Autónoma de Buenos Aires",
            province="Ciudad Autónoma de Buenos Aires",
            latitude=-34.60 - number * 0.01,
            longitude=-58.38 - number * 0.01,
            stock_scale=1.0,
        )
        for number in range(1, ESTABLISHMENT_COUNT + 1)
    )


def _users() -> tuple[ReferenceUser, ...]:
    every_establishment = tuple(
        _establishment_key(number) for number in range(1, ESTABLISHMENT_COUNT + 1)
    )
    field_workers = tuple(
        ReferenceUser(
            key=f"field_worker_{number:02d}",
            email=f"loadtest.relevador{number:02d}@tpp.com",
            name=f"Relevador {number:02d}",
            last_name=MARKER,
            role=UserRole.FIELD_WORKER,
            approved_establishments=(_establishment_key(number),),
        )
        for number in range(1, ESTABLISHMENT_COUNT + 1)
    )
    return (
        ReferenceUser(
            key="admin",
            email="loadtest.admin@tpp.com",
            name="Admin",
            last_name=MARKER,
            role=UserRole.ADMIN,
        ),
        ReferenceUser(
            key="analyst",
            email="loadtest.analista@tpp.com",
            name="Analista",
            last_name=MARKER,
            role=UserRole.ANALYST,
            approved_establishments=every_establishment,
        ),
        *field_workers,
    )


def _readings(age_years: int, variation: int) -> tuple[Reading, ...]:
    # A rough growth curve, so the WHO alerts get a realistic mix of statuses.
    height_cm = 75.0 + 6.0 * age_years + variation
    weight_kg = 10.0 + 3.0 * age_years + variation / 2
    return tuple(
        Reading(
            days_ago=30 + 120 * reading,
            weight_kg=round(weight_kg - reading * 0.5, 1),
            height_cm=round(height_cm - reading * 1.5, 1),
        )
        for reading in range(READINGS_PER_SUBJECT)
    )


def _subjects() -> tuple[ReferenceSubject, ...]:
    subjects = []
    for establishment in range(1, ESTABLISHMENT_COUNT + 1):
        for number in range(SUBJECTS_PER_ESTABLISHMENT):
            index = (establishment - 1) * SUBJECTS_PER_ESTABLISHMENT + number
            name, sex = _NAMES[index % len(_NAMES)]
            age_years = 1 + index % 17
            subjects.append(
                ReferenceSubject(
                    key=f"{_establishment_key(establishment)}_{number:03d}",
                    dni=_FIRST_DNI + index,
                    sex=sex,
                    name=name,
                    last_name=f"{MARKER} {_LAST_NAMES[index % len(_LAST_NAMES)]}",
                    age_years=age_years,
                    days_past_birthday=index % 365,
                    establishment=_establishment_key(establishment),
                    readings=_readings(age_years, variation=index % 7 - 3),
                    is_rural=index % 4 == 0,
                    is_indigenous=index % 10 == 0,
                )
            )
    return tuple(subjects)


ESTABLISHMENTS = _establishments()
USERS = _users()
SUBJECTS = _subjects()
