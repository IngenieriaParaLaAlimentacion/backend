import math
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex
from app.reference_data.anthropometry import (
    _adult_alerts,
    _child_alerts,
    age_in_months,
    compute_bmi_z_score,
    evaluate_alerts,
)


class TestAgeInMonths:
    def test_exact_birthday(self):
        assert (
            age_in_months(date(2010, 3, 15), datetime(2020, 3, 15, tzinfo=timezone.utc))
            == 120
        )

    def test_birthday_not_yet_reached_this_month(self):
        assert (
            age_in_months(date(2010, 3, 20), datetime(2020, 3, 15, tzinfo=timezone.utc))
            == 119
        )

    def test_birthday_already_passed_this_month(self):
        assert (
            age_in_months(date(2010, 3, 10), datetime(2020, 3, 15, tzinfo=timezone.utc))
            == 120
        )

    def test_newborn_same_day(self):
        assert (
            age_in_months(date(2024, 1, 1), datetime(2024, 1, 1, tzinfo=timezone.utc))
            == 0
        )

    def test_does_not_go_negative(self):
        assert (
            age_in_months(date(2024, 6, 1), datetime(2024, 1, 1, tzinfo=timezone.utc))
            == 0
        )


class TestComputeBmiZScore:
    def test_returns_none_when_no_lms_data(self):
        with patch("app.reference_data.anthropometry.WHO_BMI_LMS", {}):
            assert compute_bmi_z_score(20.0, Sex.MALE, 60) is None

    def test_power_formula(self):
        # λ=1, M=16.0, S=0.1 → z = (bmi/M - 1) / (λ * S) = (17.6/16 - 1) / 0.1 = 1.0
        lms = {("male", 60): (1.0, 16.0, 0.1)}
        with patch("app.reference_data.anthropometry.WHO_BMI_LMS", lms):
            z = compute_bmi_z_score(17.6, Sex.MALE, 60)
        assert z == pytest.approx(1.0)

    def test_log_formula_when_lambda_near_zero(self):
        # λ≈0, M=16.0, S=0.1 → z = ln(bmi/M) / S; bmi = M*e^(z*S) with z=1.0
        lms = {("male", 60): (0.0, 16.0, 0.1)}
        bmi = 16.0 * math.exp(0.1)
        with patch("app.reference_data.anthropometry.WHO_BMI_LMS", lms):
            z = compute_bmi_z_score(bmi, Sex.MALE, 60)
        assert z == pytest.approx(1.0)

    def test_female_sex_uses_female_key(self):
        lms = {("female", 60): (1.0, 15.0, 0.1)}
        with patch("app.reference_data.anthropometry.WHO_BMI_LMS", lms):
            assert compute_bmi_z_score(15.0, Sex.FEMALE, 60) == pytest.approx(0.0)


class TestChildAlerts:
    def test_severely_wasted(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=-3.5
        ):
            alerts = _child_alerts(10.0, Sex.MALE, 60)
        assert alerts[0][0] == AlertType.SEVERELY_WASTED
        assert alerts[0][1] == AlertSeverity.CRITICAL

    def test_wasted(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=-2.5
        ):
            alerts = _child_alerts(12.0, Sex.MALE, 60)
        assert alerts[0][0] == AlertType.WASTED
        assert alerts[0][1] == AlertSeverity.HIGH

    def test_obese(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=3.5
        ):
            alerts = _child_alerts(25.0, Sex.MALE, 60)
        assert alerts[0][0] == AlertType.OBESE
        assert alerts[0][1] == AlertSeverity.HIGH

    def test_overweight(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=2.5
        ):
            alerts = _child_alerts(22.0, Sex.MALE, 60)
        assert alerts[0][0] == AlertType.OVERWEIGHT
        assert alerts[0][1] == AlertSeverity.MEDIUM

    def test_normal_range_no_alert(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=0.5
        ):
            assert _child_alerts(16.0, Sex.MALE, 60) == []

    def test_no_who_data_returns_empty(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=None
        ):
            assert _child_alerts(16.0, Sex.MALE, 60) == []

    def test_boundary_z_exactly_minus3_is_wasted_not_severely(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=-3.0
        ):
            alerts = _child_alerts(10.0, Sex.MALE, 60)
        assert alerts[0][0] == AlertType.WASTED

    def test_boundary_z_exactly_2_is_no_alert(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=2.0
        ):
            assert _child_alerts(20.0, Sex.MALE, 60) == []

    def test_boundary_z_exactly_3_is_overweight_not_obese(self):
        with patch(
            "app.reference_data.anthropometry.compute_bmi_z_score", return_value=3.0
        ):
            alerts = _child_alerts(24.0, Sex.MALE, 60)
        assert alerts[0][0] == AlertType.OVERWEIGHT


class TestAdultAlerts:
    def test_severe_underweight(self):
        alerts = _adult_alerts(15.9)
        assert alerts[0][0] == AlertType.SEVERE_UNDERWEIGHT
        assert alerts[0][1] == AlertSeverity.CRITICAL

    def test_underweight(self):
        alerts = _adult_alerts(17.0)
        assert alerts[0][0] == AlertType.UNDERWEIGHT
        assert alerts[0][1] == AlertSeverity.HIGH

    def test_normal_no_alert(self):
        assert _adult_alerts(22.0) == []

    def test_overweight(self):
        alerts = _adult_alerts(27.0)
        assert alerts[0][0] == AlertType.OVERWEIGHT
        assert alerts[0][1] == AlertSeverity.MEDIUM

    def test_obese(self):
        alerts = _adult_alerts(32.0)
        assert alerts[0][0] == AlertType.OBESE
        assert alerts[0][1] == AlertSeverity.HIGH

    def test_boundary_bmi_16_is_underweight_not_severe(self):
        assert _adult_alerts(16.0)[0][0] == AlertType.UNDERWEIGHT

    def test_boundary_bmi_25_is_overweight(self):
        assert _adult_alerts(25.0)[0][0] == AlertType.OVERWEIGHT

    def test_boundary_bmi_30_is_obese(self):
        assert _adult_alerts(30.0)[0][0] == AlertType.OBESE

    def test_boundary_bmi_18_5_is_normal(self):
        assert _adult_alerts(18.5) == []


class TestEvaluateAlerts:
    def test_routes_child_path_for_age_under_228_months(self):
        birth = date(2020, 1, 1)
        measured = datetime(2024, 1, 1, tzinfo=timezone.utc)  # ~48 months
        with patch(
            "app.reference_data.anthropometry._child_alerts", return_value=[]
        ) as mock:
            evaluate_alerts(16.0, Sex.MALE, birth, measured)
        mock.assert_called_once()

    def test_routes_adult_path_for_age_over_228_months(self):
        birth = date(1990, 1, 1)
        measured = datetime(2024, 1, 1, tzinfo=timezone.utc)  # ~408 months
        with patch(
            "app.reference_data.anthropometry._adult_alerts", return_value=[]
        ) as mock:
            evaluate_alerts(22.0, Sex.MALE, birth, measured)
        mock.assert_called_once()

    def test_exactly_228_months_uses_child_path(self):
        # 228 months = 19 years exactly → boundary belongs to child path (months <= 228)
        birth = date(2005, 1, 1)
        measured = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with patch(
            "app.reference_data.anthropometry._child_alerts", return_value=[]
        ) as child_mock:
            with patch(
                "app.reference_data.anthropometry._adult_alerts", return_value=[]
            ) as adult_mock:
                evaluate_alerts(18.0, Sex.FEMALE, birth, measured)
        child_mock.assert_called_once()
        adult_mock.assert_not_called()
