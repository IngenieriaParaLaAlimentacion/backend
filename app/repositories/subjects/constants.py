"""Sort clause maps for the subjects repositories.

Each map turns a sort-order enum value into the SQLAlchemy order clause(s) its
listing applies. They live here rather than beside the queries so a repository
file stays focused on persistence logic.

Each pairs the sort column with `id` as a tiebreaker, so subjects sharing a
value still page consistently instead of shuffling between requests, and an
export lands in a reproducible order.

A KeyError on an unmapped value is intentional: it surfaces a missing case
immediately rather than silently falling back to an arbitrary order.
"""

from sqlalchemy import asc, desc

from app.domain.subject import SubjectSortOrder
from app.models.subjects.subject import Subject

SUBJECT_SORT_CLAUSES = {
    SubjectSortOrder.CREATED_AT_DESC: (desc(Subject.created_at), desc(Subject.id)),
    SubjectSortOrder.CREATED_AT_ASC: (asc(Subject.created_at), asc(Subject.id)),
    SubjectSortOrder.NAME_ASC: (asc(Subject.name), asc(Subject.id)),
    SubjectSortOrder.NAME_DESC: (desc(Subject.name), desc(Subject.id)),
    SubjectSortOrder.BIRTH_DATE_ASC: (asc(Subject.birth_date), asc(Subject.id)),
    SubjectSortOrder.BIRTH_DATE_DESC: (desc(Subject.birth_date), desc(Subject.id)),
}
