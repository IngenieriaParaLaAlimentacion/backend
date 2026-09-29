from fastapi import status

from tests.integration.urls import SURVEYS_URL

NOW = "2024-06-01T12:00:00Z"


async def _make_establishment(place_id: str = "place-test-002"):
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    async with AsyncSessionLocal() as session:
        establishment = Establishment(
            name="Otro Centro",
            formatted_address="Otra Calle 456",
            latitude=-31.4,
            longitude=-64.2,
            place_id=place_id,
            city="Cordoba",
            province="Cordoba",
        )
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
        return establishment


async def _make_subject(dni: int = 33444555):
    from datetime import date

    from app.db.database import AsyncSessionLocal
    from app.models.subjects.subject import Sex, Subject

    async with AsyncSessionLocal() as session:
        subject = Subject(
            dni=dni,
            sex=Sex.MALE,
            name="Otro",
            last_name="Sujeto",
            birth_date=date(1985, 3, 14),
        )
        session.add(subject)
        await session.commit()
        await session.refresh(subject)
        return subject


async def _create_survey(client, headers, **overrides):
    body = {
        "name": overrides.pop("name", "Encuesta A"),
        "description": overrides.pop("description", None),
        "response_target": overrides.pop("response_target", "anonymous"),
        "requires_response_number": overrides.pop("requires_response_number", True),
        "questions": overrides.pop(
            "questions",
            [
                {
                    "text": "¿Comió hoy?",
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [{"text": "Sí"}, {"text": "No"}],
                },
                {
                    "text": "Comentarios",
                    "response_type": "text",
                    "is_required": False,
                    "options": [],
                },
            ],
        ),
    }
    response = await client.post(SURVEYS_URL, json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def _valid_answers(survey: dict) -> dict:
    """A minimal valid answer set: only the required single_choice question."""
    question = survey["questions"][0]
    return {question["id"]: question["options"][0]["id"]}


def _response_body(survey_id, answers, response_number: int = 1, **overrides) -> dict:
    """Build a submission body for the default (anonymous) survey.

    Anonymous surveys carry no target, so nothing else is sent. Tests covering
    subject- or establishment-targeted surveys pass ``subject_id=`` or
    ``establishment_id=`` explicitly.
    """
    body = {
        "survey_id": str(survey_id),
        "answers": answers,
        "response_number": response_number,
        "event_at": NOW,
    }
    body.update(overrides)
    return body
