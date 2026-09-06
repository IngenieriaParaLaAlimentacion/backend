"""Sort clause maps for the surveys repositories.

Each map turns a sort-order enum value into the SQLAlchemy order clause(s) its
listing applies. They live here rather than beside the queries so a repository
file stays focused on persistence logic.

Each pairs the sort column with `id` as a tiebreaker, so rows sharing a value
still page consistently instead of shuffling between requests, and an export
lands in a reproducible order. Survey names sort case-insensitively, matching
how the listing presents them.

A KeyError on an unmapped value is intentional: it surfaces a missing case
immediately rather than silently falling back to an arbitrary order.
"""

from sqlalchemy import asc, desc, func

from app.domain.survey import SurveySortOrder
from app.domain.survey_response import SurveyResponseSortOrder
from app.models.surveys.survey import Survey
from app.models.surveys.survey_response import SurveyResponse

SURVEY_SORT_CLAUSES = {
    SurveySortOrder.NAME_ASC: (asc(func.lower(Survey.name)), asc(Survey.id)),
    SurveySortOrder.NAME_DESC: (desc(func.lower(Survey.name)), desc(Survey.id)),
    SurveySortOrder.NEWEST: (desc(Survey.created_at), desc(Survey.id)),
    SurveySortOrder.OLDEST: (asc(Survey.created_at), asc(Survey.id)),
}

SURVEY_RESPONSE_SORT_CLAUSES = {
    SurveyResponseSortOrder.EVENT_AT_DESC: (
        desc(SurveyResponse.event_at),
        desc(SurveyResponse.id),
    ),
    SurveyResponseSortOrder.EVENT_AT_ASC: (
        asc(SurveyResponse.event_at),
        asc(SurveyResponse.id),
    ),
    SurveyResponseSortOrder.CREATED_AT_DESC: (
        desc(SurveyResponse.created_at),
        desc(SurveyResponse.id),
    ),
    SurveyResponseSortOrder.CREATED_AT_ASC: (
        asc(SurveyResponse.created_at),
        asc(SurveyResponse.id),
    ),
}
