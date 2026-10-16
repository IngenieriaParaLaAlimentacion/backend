import uuid

from fastapi import status

from tests.integration.helpers import responses_url
from tests.integration.urls import MEASUREMENTS_URL, SUBJECTS_URL, SURVEYS_URL

ACTIVITY_URL = "/api/v1/users/me/activity"


FOOD_INTAKES_URL = "/api/v1/food-intakes"


FOOD_OUTFLOWS_URL = "/api/v1/food-outflows"


def _movement_body(establishment_id, lines, **overrides):
    return {
        "id": str(uuid.uuid4()),
        "establishment_id": str(establishment_id),
        "comments": None,
        "source": "manual",
        "items": [
            {"food_id": str(food_id), "quantity": str(quantity)}
            for food_id, quantity in lines
        ],
        **overrides,
    }


async def _create_food_intake(
    client, headers, establishment_id, occurred_at, lines, **overrides
):
    intake_fields = {"origin_type": "other", "is_recurring": False, **overrides}
    body = _movement_body(
        establishment_id,
        lines,
        occurred_at=occurred_at,
        **intake_fields,
    )
    response = await client.post(FOOD_INTAKES_URL, json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


async def _create_food_outflow(
    client, headers, establishment_id, occurred_at, lines, **overrides
):
    """Register an outflow.

    Outflows draw down stock and answer 409 /errors/insufficient-stock on an
    insufficient balance, so every caller must register an intake covering the
    same foods first.
    """
    body = _movement_body(establishment_id, lines, occurred_at=occurred_at, **overrides)
    response = await client.post(FOOD_OUTFLOWS_URL, json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


def _subject_body(dni: int, **overrides):
    return {
        "dni": dni,
        "sex": "male",
        "name": "Juan",
        "last_name": "Perez",
        "birth_date": "2010-01-01",
        "is_rural": False,
        "is_indigenous": False,
        **overrides,
    }


async def _create_subject(client, headers, dni: int, **overrides):
    response = await client.post(
        SUBJECTS_URL, json=_subject_body(dni, **overrides), headers=headers
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


def _measurement_body(subject_id, establishment_id, measured_at, **overrides):
    return {
        "subject_id": str(subject_id),
        "establishment_id": str(establishment_id),
        "weight_kg": 70.0,
        "height_cm": 170.0,
        "measured_at": measured_at,
        **overrides,
    }


async def _create_measurement(
    client, headers, subject_id, establishment_id, measured_at, **overrides
):
    response = await client.post(
        MEASUREMENTS_URL,
        json=_measurement_body(subject_id, establishment_id, measured_at, **overrides),
        headers=headers,
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


async def _create_survey(
    client,
    author_headers,
    name: str = "Encuesta A",
    response_target: str = "anonymous",
):
    body = {
        "name": name,
        "description": None,
        "response_target": response_target,
        "questions": [
            {
                "text": "¿Comió hoy?",
                "response_type": "single_choice",
                "is_required": True,
                "options": [{"text": "Sí"}, {"text": "No"}],
            }
        ],
    }
    response = await client.post(SURVEYS_URL, json=body, headers=author_headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


async def _submit_survey_response(
    client, headers, survey, event_at, response_number: int | None = 1, **overrides
):
    """Submit to an anonymous survey, which carries no target entity."""
    question = survey["questions"][0]
    body = {
        "survey_id": survey["id"],
        "answers": {question["id"]: question["options"][0]["id"]},
        "response_number": response_number,
        "event_at": event_at,
        **overrides,
    }
    response = await client.post(
        responses_url(survey["id"]), json=body, headers=headers
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]
