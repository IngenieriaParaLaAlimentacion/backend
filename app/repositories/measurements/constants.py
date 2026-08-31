"""Sort clause maps for the measurements repositories.

Each map turns a sort-order enum value into the SQLAlchemy order clause(s) its
listing applies. They live here rather than beside the queries so a repository
file stays focused on persistence logic.

Each pairs the sort column with `id` as a tiebreaker, so measurements sharing a
value (same weight, same day) still page consistently instead of shuffling
between requests, and an export lands in a reproducible order.

A KeyError on an unmapped value is intentional: it surfaces a missing case
immediately rather than silently falling back to an arbitrary order.
"""

from sqlalchemy import asc, desc

from app.domain.measurement import MeasurementSortOrder
from app.models.measurements.measurement import Measurement

MEASUREMENT_SORT_CLAUSES = {
    MeasurementSortOrder.DATE_DESC: (
        desc(Measurement.measured_at),
        desc(Measurement.id),
    ),
    MeasurementSortOrder.DATE_ASC: (asc(Measurement.measured_at), asc(Measurement.id)),
    MeasurementSortOrder.WEIGHT_DESC: (
        desc(Measurement.weight_kg),
        desc(Measurement.id),
    ),
    MeasurementSortOrder.WEIGHT_ASC: (asc(Measurement.weight_kg), asc(Measurement.id)),
    MeasurementSortOrder.HEIGHT_DESC: (
        desc(Measurement.height_cm),
        desc(Measurement.id),
    ),
    MeasurementSortOrder.HEIGHT_ASC: (asc(Measurement.height_cm), asc(Measurement.id)),
}
