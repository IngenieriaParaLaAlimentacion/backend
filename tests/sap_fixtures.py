from app.domain.measurement_assessment import Indicator, StatureMethod
from app.domain.subject import Sex
from app.reference_data.sap_reference import SapRuleset


def synthetic_sap_ruleset() -> SapRuleset:
    """Toy curves for tests. These values do not represent a clinical reference."""
    references = []
    for indicator, first, last, median, sigma, method in (
        (Indicator.LENGTH_FOR_AGE, 0, 23, 70, 5, StatureMethod.RECUMBENT),
        (Indicator.WEIGHT_FOR_AGE, 0, 23, 10, 1, None),
        (Indicator.BMI_FOR_AGE, 24, 228, 16, 2, None),
        (Indicator.HEIGHT_FOR_AGE, 24, 228, 100, 5, StatureMethod.STANDING),
    ):
        references.append(
            {
                "indicator": indicator,
                "reference_version": "synthetic-table",
                "source": "Generated for tests",
                "first_month": first,
                "last_month": last,
                "age_unit": "months",
                "formula": "standard",
                "stature_method": method,
                "alternate_method_offset_cm": 0.5 if method else None,
                "bands": [
                    {
                        "lower": None,
                        "upper": -2,
                        "include_lower": False,
                        "include_upper": False,
                        "classification": "low",
                        "severity": "high",
                    },
                    {
                        "lower": -2,
                        "upper": 2,
                        "include_lower": True,
                        "include_upper": False,
                        "classification": "normal",
                        "severity": None,
                    },
                    {
                        "lower": 2,
                        "upper": None,
                        "include_lower": True,
                        "include_upper": False,
                        "classification": "high",
                        "severity": "medium",
                    },
                ],
                "rows": [
                    {
                        "sex": sex,
                        "age": age,
                        "lambda": 0.0,
                        "median": median,
                        "sigma": sigma,
                    }
                    for sex in Sex
                    for age in range(first, last + 1)
                ],
            }
        )
    return SapRuleset.model_validate(
        {
            "schema_version": 1,
            "version": "synthetic-test",
            "pediatric_max_month": 228,
            "references": references,
        }
    )
