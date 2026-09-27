"""Helpers shared by several integration test modules."""

from tests.integration.urls import SURVEYS_URL


def bmi_for(weight_kg: float, height_cm: float) -> float:
    """Body mass index for the given weight and height."""
    return weight_kg / (height_cm / 100) ** 2


def responses_url(survey_id, *parts) -> str:
    """Path of a survey's responses collection, extended with ``parts``."""
    segments = [SURVEYS_URL, str(survey_id), "responses"] + [str(p) for p in parts]
    return "/".join(segments)
