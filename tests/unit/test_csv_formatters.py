from datetime import date, datetime, timezone

import pytest

from app.domain.measurement import AlertType, NutritionalStatus
from app.domain.subject import Sex
from app.domain.survey import SurveyResponseTarget
from app.services.exporters.csv.formatters import (
    ALERT_TYPE_LABELS,
    NUTRITIONAL_STATUS_LABELS,
    SEX_LABELS,
    SURVEY_TARGET_LABELS,
    format_age,
    format_alerts,
    format_bool,
    format_date,
    format_datetime,
    format_decimal,
    format_int,
    format_nutritional_status,
    format_person,
    format_sex,
    format_survey_target,
    join_values,
)


class _Alert:
    def __init__(self, alert_type: AlertType):
        self.alert_type = alert_type


class TestDates:
    def test_date_uses_argentine_order(self):
        assert format_date(date(2015, 3, 14)) == "14/03/2015"

    def test_datetime_converts_utc_to_argentine_local_time(self):
        # 10:30 UTC is 07:30 in Buenos Aires (UTC-3).
        utc = datetime(2015, 3, 14, 10, 30, tzinfo=timezone.utc)
        assert format_datetime(utc) == "14/03/2015 07:30"

    def test_naive_datetime_is_read_as_utc(self):
        # Timestamps are stored naive-UTC, so the export must match the UI.
        naive = datetime(2015, 3, 14, 10, 30)
        assert format_datetime(naive) == "14/03/2015 07:30"

    def test_conversion_can_cross_the_date_boundary(self):
        utc = datetime(2015, 3, 15, 1, 0, tzinfo=timezone.utc)
        assert format_datetime(utc) == "14/03/2015 22:00"


class TestNumbers:
    def test_decimal_uses_a_comma(self):
        assert format_decimal(18.5) == "18,50"

    def test_decimal_rounds_to_two_digits_by_default(self):
        assert format_decimal(18.516) == "18,52"

    def test_decimal_honours_a_digit_count(self):
        assert format_decimal(18.5, digits=1) == "18,5"

    def test_int_is_rendered_plainly(self):
        # DNIs must not pick up a thousands separator.
        assert format_int(30123456) == "30123456"

    def test_age_is_rendered_as_years_and_months(self):
        assert format_age(63) == "5a 3m"

    def test_age_below_a_year(self):
        assert format_age(7) == "0a 7m"


class TestText:
    def test_person_joins_name_and_last_name(self):
        assert format_person("Ana", "Pérez") == "Ana Pérez"

    def test_person_skips_a_missing_half(self):
        assert format_person("Ana", None) == "Ana"

    def test_join_values_is_comma_separated(self):
        assert join_values(["Sobrepeso", "Obesidad"]) == "Sobrepeso, Obesidad"

    def test_join_values_drops_blanks(self):
        assert join_values(["Sobrepeso", "", "Obesidad"]) == "Sobrepeso, Obesidad"

    def test_bool_uses_the_column_labels(self):
        assert format_bool(True, "Activa", "Inactiva") == "Activa"
        assert format_bool(False, "Activa", "Inactiva") == "Inactiva"


class TestEnumLabels:
    @pytest.mark.parametrize("member", list(Sex))
    def test_every_sex_has_a_label(self, member):
        assert SEX_LABELS[member]

    @pytest.mark.parametrize("member", list(NutritionalStatus))
    def test_every_nutritional_status_has_a_label(self, member):
        assert NUTRITIONAL_STATUS_LABELS[member]

    @pytest.mark.parametrize("member", list(AlertType))
    def test_every_alert_type_has_a_label(self, member):
        assert ALERT_TYPE_LABELS[member]

    @pytest.mark.parametrize("member", list(SurveyResponseTarget))
    def test_every_survey_target_has_a_label(self, member):
        assert SURVEY_TARGET_LABELS[member]

    def test_sex_renders_in_spanish(self):
        assert format_sex(Sex.FEMALE) == "Femenino"

    def test_survey_target_renders_in_spanish(self):
        assert format_survey_target(SurveyResponseTarget.SUBJECT) == "Sujeto"

    def test_alerts_are_joined_into_one_cell(self):
        alerts = [_Alert(AlertType.OBESE), _Alert(AlertType.UNDERWEIGHT)]
        assert format_alerts(alerts) == "Obesidad, Bajo peso"

    def test_no_alerts_is_an_empty_cell(self):
        assert format_alerts([]) == ""


class TestMissingValues:
    @pytest.mark.parametrize(
        "formatter",
        [
            format_date,
            format_datetime,
            format_decimal,
            format_int,
            format_age,
            format_sex,
            format_nutritional_status,
            format_survey_target,
        ],
    )
    def test_none_renders_as_an_empty_cell(self, formatter):
        assert formatter(None) == ""

    def test_bool_none_renders_as_an_empty_cell(self):
        assert format_bool(None, "Activa", "Inactiva") == ""

    def test_never_measured_is_not_the_same_as_normal(self):
        # A subject with no measurement has no status; NORMAL means "measured
        # and healthy".
        assert format_nutritional_status(None) == ""
        assert format_nutritional_status(NutritionalStatus.NORMAL) == "Normal"
