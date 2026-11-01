"""Sort clause maps for the establishments repositories.

Each map turns a sort-order enum value into the SQLAlchemy order clause(s) its
listing applies. They live here rather than beside the queries so a repository
file stays focused on persistence logic.

Most pair the sort column with `id` as a tiebreaker, so rows sharing a value
still page consistently instead of shuffling between requests, and an export
lands in a reproducible order.

A KeyError on an unmapped value is intentional throughout: it surfaces a missing
case immediately rather than silently falling back to an arbitrary order.
"""

from sqlalchemy import asc, desc, extract, func

from app.domain.establishment import (
    EstablishmentCreationRequestSortOrder,
    EstablishmentSortOrder,
)
from app.domain.establishment_dashboard import EstablishmentSubjectSortOrder
from app.models.establishments.establishment import Establishment
from app.models.establishments.establishment_request import EstablishmentRequest
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject

# Completed months between a subject's birth date and the moment they were
# measured. Postgres ``age()`` returns an interval of full years/months/days,
# matching ``app.utils.dates.completed_months_between``.
AGE_MONTHS = extract(
    "year", func.age(Measurement.measured_at, Subject.birth_date)
) * 12 + extract("month", func.age(Measurement.measured_at, Subject.birth_date))

ESTABLISHMENT_SORT_CLAUSES = {
    EstablishmentSortOrder.NEWEST: (
        desc(Establishment.created_at),
        desc(Establishment.id),
    ),
    EstablishmentSortOrder.OLDEST: (
        asc(Establishment.created_at),
        asc(Establishment.id),
    ),
    EstablishmentSortOrder.NAME_ASC: (asc(Establishment.name), asc(Establishment.id)),
    EstablishmentSortOrder.NAME_DESC: (
        desc(Establishment.name),
        desc(Establishment.id),
    ),
    EstablishmentSortOrder.CITY_ASC: (asc(Establishment.city), asc(Establishment.id)),
    EstablishmentSortOrder.CITY_DESC: (
        desc(Establishment.city),
        desc(Establishment.id),
    ),
    EstablishmentSortOrder.PROVINCE_ASC: (
        asc(Establishment.province),
        asc(Establishment.id),
    ),
    EstablishmentSortOrder.PROVINCE_DESC: (
        desc(Establishment.province),
        desc(Establishment.id),
    ),
}

CREATION_REQUEST_SORT_CLAUSES = {
    EstablishmentCreationRequestSortOrder.NEWEST: desc(EstablishmentRequest.created_at),
    EstablishmentCreationRequestSortOrder.OLDEST: asc(EstablishmentRequest.created_at),
}

# Older birth_date means older subject, hence the inversion on the AGE_* orders.
SUBJECT_SORT_CLAUSES = {
    EstablishmentSubjectSortOrder.MEASURED_AT_DESC: desc(Measurement.measured_at),
    EstablishmentSubjectSortOrder.MEASURED_AT_ASC: asc(Measurement.measured_at),
    EstablishmentSubjectSortOrder.NAME_ASC: asc(Subject.last_name),
    EstablishmentSubjectSortOrder.NAME_DESC: desc(Subject.last_name),
    EstablishmentSubjectSortOrder.BMI_DESC: desc(Measurement.bmi),
    EstablishmentSubjectSortOrder.BMI_ASC: asc(Measurement.bmi),
    EstablishmentSubjectSortOrder.AGE_DESC: asc(Subject.birth_date),
    EstablishmentSubjectSortOrder.AGE_ASC: desc(Subject.birth_date),
}
