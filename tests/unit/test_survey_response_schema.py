from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from app.models.surveys.survey import Survey
from app.models.surveys.survey_response import SurveyResponse
from app.models.surveys.survey_response_edit import SurveyResponseEdit
from app.schemas.surveys.survey_response_schema import (
    SurveyResponseEditRequest,
    SurveyResponseRequest,
)


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


def test_response_number_columns_and_survey_setting_are_nullable():
    assert Survey.__table__.c.requires_response_number.nullable is True
    assert SurveyResponse.__table__.c.response_number.nullable is True
    assert SurveyResponseEdit.__table__.c.response_number.nullable is True


def test_response_number_migration_is_linear_off_develop():
    """The migration stays a single unbranched line off develop.

    It is no longer the head — later features stack on top of it — so the
    guard checks its parent and that the tree still has exactly one head.
    """
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision("d47f2a9c1e63")

    assert migration.down_revision == "c8e3d5a91f74"
    assert len(scripts.get_heads()) == 1


def test_submit_and_edit_accept_missing_or_null_response_number():
    common = {"answers": {}, "event_at": datetime.now(timezone.utc)}

    assert SurveyResponseRequest(id=uuid4(), **common).response_number is None
    assert (
        SurveyResponseRequest(
            id=uuid4(), response_number=None, **common
        ).response_number
        is None
    )
    assert SurveyResponseEditRequest(**common).response_number is None


@pytest.mark.parametrize("value", [0, 1_000_000])
def test_supplied_response_number_keeps_range_validation(value):
    with pytest.raises(ValidationError):
        SurveyResponseRequest(
            id=uuid4(),
            answers={},
            response_number=value,
            event_at=datetime.now(timezone.utc),
        )
