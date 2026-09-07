from app.models.surveys.survey_response import SurveyResponse


def test_response_number_index_is_non_unique():
    """The response-number index supports filters without enforcing uniqueness."""
    index = next(
        index
        for index in SurveyResponse.__table__.indexes
        if index.name == "ix_survey_responses_survey_response_number"
    )

    assert tuple(column.name for column in index.columns) == (
        "survey_id",
        "response_number",
    )
    assert index.unique is False
