import uuid

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import func, select

from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

SURVEY_RESPONSES_URL = "/api/v1/survey-responses"
SURVEYS_URL = "/api/v1/surveys"

NOW = "2024-06-01T12:00:00Z"


async def _make_establishment(place_id: str = "place-test-002"):
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

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


@pytest_asyncio.fixture
async def admin_user(make_user_with_role):
    return await make_user_with_role(UserRole.ADMIN)


@pytest_asyncio.fixture
async def superadmin_user(make_user_with_role):
    return await make_user_with_role(UserRole.SUPERADMIN)


@pytest_asyncio.fixture
async def analyst_user(make_user_with_role):
    return await make_user_with_role(UserRole.ANALYST)


@pytest_asyncio.fixture
async def field_worker_without_access(make_user_with_role):
    return await make_user_with_role(UserRole.FIELD_WORKER)


async def _create_survey(client, headers, **overrides):
    body = {
        "name": overrides.pop("name", "Encuesta A"),
        "description": overrides.pop("description", None),
        "scope": overrides.pop("scope", "generic"),
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
        "establishment_ids": overrides.pop("establishment_ids", []),
    }
    response = await client.post(SURVEYS_URL, json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def _valid_answers(survey: dict) -> dict:
    """A minimal valid answer set: only the required single_choice question."""
    question = survey["questions"][0]
    return {question["id"]: question["options"][0]["id"]}


def _response_body(survey_id, establishment_id, answers, **overrides) -> dict:
    body = {
        "survey_id": str(survey_id),
        "establishment_id": str(establishment_id),
        "answers": answers,
        "event_at": NOW,
    }
    body.update(overrides)
    return body


class TestSubmitAuth:
    async def test_unauthenticated_returns_401(self, client, db_establishment):
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(uuid.uuid4(), db_establishment.id, {}),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_analyst_forbidden(self, client, db_establishment, analyst_user):
        headers, _ = analyst_user
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(uuid.uuid4(), db_establishment.id, {}),
            headers=headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSubmitRoleMatrix:
    async def test_field_worker_without_access_forbidden(
        self, client, db_establishment, admin_user, field_worker_without_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_without_access
        survey = await _create_survey(client, admin_headers)
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_field_worker_with_access_succeeds(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, fw_id = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["submitted_by_id"] == str(fw_id)

    async def test_admin_succeeds(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED

    async def test_superadmin_succeeds(
        self, client, db_establishment, admin_user, superadmin_user
    ):
        admin_headers, _ = admin_user
        sa_headers, _ = superadmin_user
        survey = await _create_survey(client, admin_headers)
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=sa_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED


class TestSubmitValidation:
    async def test_missing_required_question_returns_400(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(survey["id"], db_establishment.id, {}),
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_unknown_survey_returns_404(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(uuid.uuid4(), db_establishment.id, {}),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unknown_establishment_returns_404(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(survey["id"], uuid.uuid4(), _valid_answers(survey)),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_establishment_outside_targeted_audience_returns_400(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        outside = await _make_establishment()
        survey = await _create_survey(
            client,
            headers,
            scope="targeted",
            establishment_ids=[str(db_establishment.id)],
        )
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(survey["id"], outside.id, _valid_answers(survey)),
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_multiple_choice_with_non_string_element_returns_422(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(
            client,
            headers,
            questions=[
                {
                    "text": "¿Qué alimentos consumió?",
                    "response_type": "multiple_choice",
                    "is_required": True,
                    "options": [{"text": "Verduras"}, {"text": "Frutas"}],
                }
            ],
        )
        question = survey["questions"][0]
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                db_establishment.id,
                {question["id"]: [{"not": "a valid option id"}]},
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_establishment_inside_targeted_audience_succeeds(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(
            client,
            headers,
            scope="targeted",
            establishment_ids=[str(db_establishment.id)],
        )
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED


class TestSubmitIdempotentReplay:
    async def test_same_client_id_replays_without_duplicate_row(
        self, client, db_establishment, admin_user
    ):
        from app.models.survey_response import SurveyResponse

        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response_id = str(uuid.uuid4())
        body = _response_body(
            survey["id"], db_establishment.id, _valid_answers(survey), id=response_id
        )

        first = await client.post(SURVEY_RESPONSES_URL, json=body, headers=headers)
        assert first.status_code == status.HTTP_201_CREATED

        second = await client.post(SURVEY_RESPONSES_URL, json=body, headers=headers)
        assert second.status_code == status.HTTP_200_OK
        assert second.json() == first.json()

        from app.db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            count = await session.execute(
                select(func.count()).select_from(SurveyResponse)
            )
            assert count.scalar_one() == 1


class TestResponseCount:
    async def test_submit_increments_survey_response_count(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        get_response = await client.get(
            f"{SURVEYS_URL}/{survey['id']}", headers=headers
        )
        assert get_response.json()["response_count"] == 1


class TestEdit:
    async def test_missing_response_returns_404(self, client, admin_user):
        headers, _ = admin_user
        response = await client.put(
            f"{SURVEY_RESPONSES_URL}/{uuid.uuid4()}",
            json={"answers": {}, "event_at": NOW},
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_non_owner_field_worker_forbidden(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=admin_headers,
            )
        ).json()
        response = await client.put(
            f"{SURVEY_RESPONSES_URL}/{created['id']}",
            json={"answers": _valid_answers(survey), "event_at": NOW},
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_owner_field_worker_can_edit(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=fw_headers,
            )
        ).json()
        question = survey["questions"][0]
        new_answers = {question["id"]: question["options"][1]["id"]}
        response = await client.put(
            f"{SURVEY_RESPONSES_URL}/{created['id']}",
            json={"answers": new_answers, "event_at": NOW},
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["answers"] == new_answers

    async def test_admin_can_override_any_response(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=fw_headers,
            )
        ).json()
        response = await client.put(
            f"{SURVEY_RESPONSES_URL}/{created['id']}",
            json={"answers": _valid_answers(survey), "event_at": NOW},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_edit_appends_audit_row(self, client, db_establishment, admin_user):
        from app.models.survey_response_edit import SurveyResponseEdit

        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=headers,
            )
        ).json()
        await client.put(
            f"{SURVEY_RESPONSES_URL}/{created['id']}",
            json={"answers": _valid_answers(survey), "event_at": NOW},
            headers=headers,
        )

        from app.db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            count = await session.execute(
                select(func.count()).select_from(SurveyResponseEdit)
            )
            assert count.scalar_one() == 1

    async def test_last_write_wins_older_event_at_does_not_overwrite(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        original_answers = _valid_answers(survey)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"],
                    db_establishment.id,
                    original_answers,
                    event_at="2024-06-02T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()
        question = survey["questions"][0]
        older_answers = {question["id"]: question["options"][1]["id"]}

        response = await client.put(
            f"{SURVEY_RESPONSES_URL}/{created['id']}",
            json={"answers": older_answers, "event_at": "2024-06-01T00:00:00Z"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        # The edit is logged, but the response's current state is unchanged
        # since its event_at is more recent than the edit's.
        assert response.json()["answers"] == original_answers

        from app.db.database import AsyncSessionLocal
        from app.models.survey_response_edit import SurveyResponseEdit

        async with AsyncSessionLocal() as session:
            count = await session.execute(
                select(func.count()).select_from(SurveyResponseEdit)
            )
            assert count.scalar_one() == 1


class TestGetResponse:
    """The full-detail view a mobile client hits after tapping a `/me/activity`
    entry, since the activity feed only carries a summary."""

    async def test_missing_response_returns_404(self, client, admin_user):
        headers, _ = admin_user
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{uuid.uuid4()}", headers=headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_owner_field_worker_can_view_own_response(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        answers = _valid_answers(survey)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(survey["id"], db_establishment.id, answers),
                headers=fw_headers,
            )
        ).json()
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}", headers=fw_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["answers"] == answers

    async def test_non_owner_field_worker_forbidden(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=admin_headers,
            )
        ).json()
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}", headers=fw_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_admin_can_view_any_response(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=fw_headers,
            )
        ).json()
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_analyst_forbidden(
        self, client, db_establishment, admin_user, analyst_user
    ):
        admin_headers, _ = admin_user
        analyst_headers, _ = analyst_user
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=admin_headers,
            )
        ).json()
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}", headers=analyst_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestListAvailable:
    async def test_field_worker_sees_generic_and_own_targeted_only(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        other_establishment = await _make_establishment()

        await _create_survey(client, admin_headers, name="Generic Survey")
        await _create_survey(
            client,
            admin_headers,
            name="My Targeted Survey",
            scope="targeted",
            establishment_ids=[str(db_establishment.id)],
        )
        await _create_survey(
            client,
            admin_headers,
            name="Other Targeted Survey",
            scope="targeted",
            establishment_ids=[str(other_establishment.id)],
        )

        response = await client.get(f"{SURVEYS_URL}/available", headers=fw_headers)
        assert response.status_code == status.HTTP_200_OK
        names = {s["name"] for s in response.json()["items"]}
        assert names == {"Generic Survey", "My Targeted Survey"}

    async def test_field_worker_without_access_only_sees_generic(
        self, client, db_establishment, admin_user, field_worker_without_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_without_access
        await _create_survey(client, admin_headers, name="Generic Survey")
        await _create_survey(
            client,
            admin_headers,
            name="Targeted Survey",
            scope="targeted",
            establishment_ids=[str(db_establishment.id)],
        )
        response = await client.get(f"{SURVEYS_URL}/available", headers=fw_headers)
        names = {s["name"] for s in response.json()["items"]}
        assert names == {"Generic Survey"}

    async def test_admin_sees_every_active_targeted_survey(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        await _create_survey(
            client,
            headers,
            name="Targeted Anywhere",
            scope="targeted",
            establishment_ids=[str(db_establishment.id)],
        )
        response = await client.get(f"{SURVEYS_URL}/available", headers=headers)
        assert response.json()["total"] == 1

    async def test_inactive_surveys_excluded(
        self, client, admin_user, field_worker_without_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_without_access
        survey = await _create_survey(client, admin_headers, name="To Deactivate")
        await client.patch(
            f"{SURVEYS_URL}/{survey['id']}/status",
            json={"is_active": False},
            headers=admin_headers,
        )
        response = await client.get(f"{SURVEYS_URL}/available", headers=fw_headers)
        assert response.json()["total"] == 0

    async def test_analyst_forbidden(self, client, analyst_user):
        headers, _ = analyst_user
        response = await client.get(f"{SURVEYS_URL}/available", headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestListBySurvey:
    async def test_shows_submitter_establishment_and_date(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, fw_id = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=fw_headers,
            )
        ).json()

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"]},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["id"] == created["id"]
        assert item["survey"]["id"] == survey["id"]
        assert item["establishment"]["id"] == str(db_establishment.id)
        assert item["submitted_by"]["id"] == str(fw_id)
        assert "event_at" in item

    async def test_orders_by_event_at_desc(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        older = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"],
                    db_establishment.id,
                    _valid_answers(survey),
                    event_at="2024-06-01T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()
        newer = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"],
                    db_establishment.id,
                    _valid_answers(survey),
                    id=str(uuid.uuid4()),
                    event_at="2024-06-05T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"]},
            headers=headers,
        )

        ids = [item["id"] for item in response.json()["items"]]
        assert ids == [newer["id"], older["id"]]

    async def test_paginates(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        for _ in range(3):
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"],
                    db_establishment.id,
                    _valid_answers(survey),
                    id=str(uuid.uuid4()),
                ),
                headers=headers,
            )

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"], "page": 1, "page_size": 2},
            headers=headers,
        )

        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3
        assert body["total_pages"] == 2

    async def test_only_returns_responses_for_requested_survey(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey_a = await _create_survey(client, headers, name="Encuesta A")
        survey_b = await _create_survey(client, headers, name="Encuesta B")
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey_a["id"], db_establishment.id, _valid_answers(survey_a)
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey_b["id"], db_establishment.id, _valid_answers(survey_b)
            ),
            headers=headers,
        )

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey_a["id"]},
            headers=headers,
        )

        assert response.json()["total"] == 1

    async def test_field_worker_forbidden(
        self, client, admin_user, field_worker_without_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_without_access
        survey = await _create_survey(client, admin_headers)

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"]},
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_allowed(self, client, admin_user, analyst_user):
        admin_headers, _ = admin_user
        analyst_headers, _ = analyst_user
        survey = await _create_survey(client, admin_headers)

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"]},
            headers=analyst_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_unknown_survey_returns_404(self, client, admin_user):
        headers, _ = admin_user
        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unauthenticated_returns_401(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.get(
            SURVEY_RESPONSES_URL, params={"survey_id": survey["id"]}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetDashboardDetail:
    async def test_shows_question_text_and_resolved_option_label(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        answers = _valid_answers(survey)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(survey["id"], db_establishment.id, answers),
                headers=headers,
            )
        ).json()

        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}/dashboard-detail",
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["answers"]) == len(survey["questions"])
        first_question = survey["questions"][0]
        answer = next(
            a for a in body["answers"] if a["question_id"] == first_question["id"]
        )
        assert answer["question_text"] == first_question["text"]
        expected_option = next(
            o
            for o in first_question["options"]
            if o["id"] == answers[first_question["id"]]
        )
        assert answer["value_label"] == expected_option["text"]

    async def test_unanswered_optional_question_has_null_value(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=headers,
            )
        ).json()

        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}/dashboard-detail",
            headers=headers,
        )

        comments_question = survey["questions"][1]
        answer = next(
            a
            for a in response.json()["answers"]
            if a["question_id"] == comments_question["id"]
        )
        assert answer["value"] is None
        assert answer["value_label"] is None

    async def test_field_worker_forbidden(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=fw_headers,
            )
        ).json()

        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}/dashboard-detail",
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_response_not_found_returns_404(self, client, admin_user):
        headers, _ = admin_user
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/{uuid.uuid4()}/dashboard-detail",
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestFiesScoring:
    @staticmethod
    def _fies_survey_body(name: str) -> dict:
        from app.data.fies_template import build_fies_template

        template = build_fies_template()
        return {
            "name": name,
            "description": template.description,
            "scope": "generic",
            "instrument_type": "fies",
            "questions": [
                {
                    "text": q.text,
                    "response_type": q.response_type.value,
                    "is_required": q.is_required,
                    "options": [{"text": o.text} for o in q.options],
                }
                for q in template.questions
            ],
            "establishment_ids": [],
        }

    async def test_fies_response_gets_partial_score(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = (
            await client.post(
                SURVEYS_URL,
                json=self._fies_survey_body("FIES Julio 2026"),
                headers=headers,
            )
        ).json()

        answers = {
            q["id"]: q["options"][0]["id"] if i < 3 else q["options"][1]["id"]
            for i, q in enumerate(survey["questions"])
        }
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(survey["id"], db_establishment.id, answers),
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["score_fies"] == 3

    async def test_fies_response_all_affirmative_scores_eight(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = (
            await client.post(
                SURVEYS_URL,
                json=self._fies_survey_body("FIES All Yes"),
                headers=headers,
            )
        ).json()
        answers = {q["id"]: q["options"][0]["id"] for q in survey["questions"]}

        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(survey["id"], db_establishment.id, answers),
            headers=headers,
        )
        assert response.json()["score_fies"] == 8

    async def test_custom_survey_response_has_null_score(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)  # default instrument_type=custom
        response = await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        assert response.json()["score_fies"] is None

    async def test_editing_answers_recalculates_score(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = (
            await client.post(
                SURVEYS_URL,
                json=self._fies_survey_body("FIES Edit Test"),
                headers=headers,
            )
        ).json()
        original_answers = {
            q["id"]: q["options"][1]["id"] for q in survey["questions"]
        }  # all "No"
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, original_answers
                ),
                headers=headers,
            )
        ).json()
        assert created["score_fies"] == 0

        new_answers = {
            q["id"]: q["options"][0]["id"] for q in survey["questions"]
        }  # all "Sí"
        edited = (
            await client.put(
                f"{SURVEY_RESPONSES_URL}/{created['id']}",
                json={"answers": new_answers, "event_at": NOW},
                headers=headers,
            )
        ).json()
        assert edited["score_fies"] == 8

    async def test_score_appears_in_dashboard_list(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = (
            await client.post(
                SURVEYS_URL,
                json=self._fies_survey_body("FIES Dashboard List"),
                headers=headers,
            )
        ).json()
        answers = {
            q["id"]: q["options"][1]["id"] for q in survey["questions"]
        }  # all "No"
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(survey["id"], db_establishment.id, answers),
            headers=headers,
        )

        list_response = await client.get(
            SURVEY_RESPONSES_URL, params={"survey_id": survey["id"]}, headers=headers
        )
        assert list_response.json()["items"][0]["score_fies"] == 0

    async def test_score_appears_in_response_detail(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = (
            await client.post(
                SURVEYS_URL,
                json=self._fies_survey_body("FIES Detail View"),
                headers=headers,
            )
        ).json()
        answers = {
            q["id"]: q["options"][0]["id"] if i < 5 else q["options"][1]["id"]
            for i, q in enumerate(survey["questions"])
        }
        created = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(survey["id"], db_establishment.id, answers),
                headers=headers,
            )
        ).json()

        detail = await client.get(
            f"{SURVEY_RESPONSES_URL}/{created['id']}/dashboard-detail",
            headers=headers,
        )
        assert detail.json()["score_fies"] == 5


class TestListFilters:
    async def test_filters_by_establishment(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        other_establishment = await _make_establishment(place_id="place-filter-001")

        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], other_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={
                "survey_id": survey["id"],
                "establishment_id": str(db_establishment.id),
            },
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["establishment"]["id"] == str(db_establishment.id)

    async def test_filters_by_event_at_range(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        old = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"],
                    db_establishment.id,
                    _valid_answers(survey),
                    event_at="2024-01-01T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()
        recent = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"],
                    db_establishment.id,
                    _valid_answers(survey),
                    id=str(uuid.uuid4()),
                    event_at="2024-06-15T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={
                "survey_id": survey["id"],
                "event_at_from": "2024-05-01T00:00:00Z",
            },
            headers=headers,
        )
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == [recent["id"]]
        assert old["id"] not in ids

    async def test_filters_by_city(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        cordoba_establishment = await _make_establishment(place_id="place-filter-002")

        buenos_aires_response = (
            await client.post(
                SURVEY_RESPONSES_URL,
                json=_response_body(
                    survey["id"], db_establishment.id, _valid_answers(survey)
                ),
                headers=headers,
            )
        ).json()
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                cordoba_establishment.id,
                _valid_answers(survey),
                id=str(uuid.uuid4()),
            ),
            headers=headers,
        )

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"], "city": "Buenos Aires"},
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == buenos_aires_response["id"]
        assert body["items"][0]["establishment"]["city"] == "Buenos Aires"

    async def test_filters_by_province(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        cordoba_establishment = await _make_establishment(place_id="place-filter-003")

        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                cordoba_establishment.id,
                _valid_answers(survey),
                id=str(uuid.uuid4()),
            ),
            headers=headers,
        )

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"], "province": "Cordoba"},
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["establishment"]["province"] == "Cordoba"

    async def test_city_filter_case_insensitive(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )

        response = await client.get(
            SURVEY_RESPONSES_URL,
            params={"survey_id": survey["id"], "city": "buenos aires"},  # lowercase
            headers=headers,
        )
        assert response.json()["total"] == 1

    async def test_no_filters_returns_all(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )

        response = await client.get(
            SURVEY_RESPONSES_URL, params={"survey_id": survey["id"]}, headers=headers
        )
        assert response.json()["total"] == 1


DASHBOARD_URL = "/api/v1/dashboard"


class TestDashboardIndicators:
    async def test_counts_all_responses_with_no_filters(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                db_establishment.id,
                _valid_answers(survey),
                event_at="2024-01-01T00:00:00Z",
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                db_establishment.id,
                _valid_answers(survey),
                id=str(uuid.uuid4()),
                event_at="2024-06-01T00:00:00Z",
            ),
            headers=headers,
        )

        response = await client.get(f"{DASHBOARD_URL}/indicators", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["response_count"] == 2
        assert body["participating_establishments_count"] == 1
        assert body["last_event_at"] == "2024-06-01T00:00:00Z"

    async def test_counts_distinct_establishments(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        other_establishment = await _make_establishment(place_id="place-indicators-001")

        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                other_establishment.id,
                _valid_answers(survey),
                id=str(uuid.uuid4()),
            ),
            headers=headers,
        )

        response = await client.get(f"{DASHBOARD_URL}/indicators", headers=headers)

        assert response.json()["participating_establishments_count"] == 2

    async def test_filters_by_survey_id(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey_a = await _create_survey(client, headers, name="Encuesta A")
        survey_b = await _create_survey(client, headers, name="Encuesta B")
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey_a["id"], db_establishment.id, _valid_answers(survey_a)
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey_b["id"], db_establishment.id, _valid_answers(survey_b)
            ),
            headers=headers,
        )

        response = await client.get(
            f"{DASHBOARD_URL}/indicators",
            params={"survey_id": survey_a["id"]},
            headers=headers,
        )

        assert response.json()["response_count"] == 1

    async def test_filters_by_event_at_range(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                db_establishment.id,
                _valid_answers(survey),
                event_at="2024-01-01T00:00:00Z",
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                db_establishment.id,
                _valid_answers(survey),
                id=str(uuid.uuid4()),
                event_at="2024-06-15T00:00:00Z",
            ),
            headers=headers,
        )

        response = await client.get(
            f"{DASHBOARD_URL}/indicators",
            params={"event_at_from": "2024-05-01T00:00:00Z"},
            headers=headers,
        )

        body = response.json()
        assert body["response_count"] == 1
        assert body["last_event_at"] == "2024-06-15T00:00:00Z"

    async def test_filters_by_city(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        cordoba_establishment = await _make_establishment(
            place_id="place-indicators-002"
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"],
                cordoba_establishment.id,
                _valid_answers(survey),
                id=str(uuid.uuid4()),
            ),
            headers=headers,
        )

        response = await client.get(
            f"{DASHBOARD_URL}/indicators",
            params={"city": "Buenos Aires"},
            headers=headers,
        )

        assert response.json()["response_count"] == 1

    async def test_no_responses_returns_zero_and_null_last_event_at(
        self, client, admin_user
    ):
        headers, _ = admin_user
        response = await client.get(f"{DASHBOARD_URL}/indicators", headers=headers)

        body = response.json()
        assert body["response_count"] == 0
        assert body["participating_establishments_count"] == 0
        assert body["last_event_at"] is None

    async def test_invalid_date_range_returns_400(self, client, admin_user):
        headers, _ = admin_user
        response = await client.get(
            f"{DASHBOARD_URL}/indicators",
            params={
                "event_at_from": "2024-06-01T00:00:00Z",
                "event_at_to": "2024-01-01T00:00:00Z",
            },
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_field_worker_forbidden(self, client, field_worker_without_access):
        headers, _ = field_worker_without_access
        response = await client.get(f"{DASHBOARD_URL}/indicators", headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_allowed(self, client, analyst_user):
        headers, _ = analyst_user
        response = await client.get(f"{DASHBOARD_URL}/indicators", headers=headers)
        assert response.status_code == status.HTTP_200_OK

    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"{DASHBOARD_URL}/indicators")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestExport:
    async def test_admin_can_export_xlsx(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            SURVEY_RESPONSES_URL,
            json=_response_body(
                survey["id"], db_establishment.id, _valid_answers(survey)
            ),
            headers=headers,
        )

        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/export",
            params={
                "survey_id": survey["id"],
                "establishment_id": str(db_establishment.id),
            },
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert "spreadsheetml" in response.headers["content-type"]
        assert response.content[:2] == b"PK"  # xlsx is a zip archive

    async def test_field_worker_forbidden(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_with_access
        survey = await _create_survey(client, admin_headers)

        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/export",
            params={
                "survey_id": survey["id"],
                "establishment_id": str(db_establishment.id),
            },
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_unknown_survey_returns_404(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/export",
            params={
                "survey_id": str(uuid.uuid4()),
                "establishment_id": str(db_establishment.id),
            },
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_export_with_no_responses_still_succeeds(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)

        response = await client.get(
            f"{SURVEY_RESPONSES_URL}/export",
            params={
                "survey_id": survey["id"],
                "establishment_id": str(db_establishment.id),
            },
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
