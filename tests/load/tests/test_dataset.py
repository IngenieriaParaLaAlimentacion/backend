"""The generated load-test dataset."""

from collections import Counter
from datetime import date
from uuid import uuid4

from app.domain.user import UserRole
from app.schemas.measurements.measurement_schema import MeasurementRequest
from app.schemas.subjects.subject_schema import SubjectRequest
from tests.load.data.dataset import (
    ESTABLISHMENTS,
    FIES_SURVEY_NAME,
    MARKER,
    SUBJECTS,
    USERS,
)


def test_subjects_have_unique_dnis_and_keys():
    assert len({subject.dni for subject in SUBJECTS}) == len(SUBJECTS)
    assert len({subject.key for subject in SUBJECTS}) == len(SUBJECTS)


def test_every_establishment_has_exactly_one_field_worker():
    # The load tests send each establishment's writes as its only field worker.
    workers = Counter(
        key
        for user in USERS
        if user.role == UserRole.FIELD_WORKER
        for key in user.approved_establishments
    )

    assert workers == Counter(spec.key for spec in ESTABLISHMENTS)


def test_every_subject_and_reading_passes_request_validation():
    today = date.today()
    for subject in SUBJECTS:
        SubjectRequest(
            id=uuid4(),
            dni=subject.dni,
            sex=subject.sex,
            name=subject.name,
            last_name=subject.last_name,
            birth_date=subject.birth_date(today),
            is_rural=subject.is_rural,
            is_indigenous=subject.is_indigenous,
        )
        for reading in subject.readings:
            MeasurementRequest(
                id=uuid4(),
                subject_id=uuid4(),
                establishment_id=uuid4(),
                weight_kg=reading.weight_kg,
                height_cm=reading.height_cm,
                measured_at=f"{today.isoformat()}T12:00:00Z",
            )


def test_every_seeded_record_carries_the_marker():
    # The marker is how load-test rows are found when cleaning the database by hand.
    assert all(MARKER in user.last_name for user in USERS)
    assert all(MARKER.lower() in user.email for user in USERS)
    assert all(MARKER in spec.name for spec in ESTABLISHMENTS)
    assert all(MARKER in subject.last_name for subject in SUBJECTS)
    assert MARKER in FIES_SURVEY_NAME
