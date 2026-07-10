import uuid

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

SURVEY_RESPONSES_URL = "/api/v1/survey-responses"
SURVEYS_URL = "/api/v1/surveys"

NOW = "2024-06-01T12:00:00Z"


async def _make_user(role: UserRole):
    """Create a real DB user for the given role and return (headers, user_id)."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserStatus
    from app.models.user import User
    from app.models.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Test",
                last_name=role.value.title(),
                email=f"{user_id}@test.com",
                role=ORMUserRole(role.value),
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    token = create_access_token(user_id, role=role)
    return {"Authorization": f"Bearer {token}"}, user_id


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
async def admin_user(app):
    return await _make_user(UserRole.ADMIN)


@pytest_asyncio.fixture
async def superadmin_user(app):
    return await _make_user(UserRole.SUPERADMIN)


@pytest_asyncio.fixture
async def analyst_user(app):
    return await _make_user(UserRole.ANALYST)


@pytest_asyncio.fixture
async def field_worker_without_access(app):
    return await _make_user(UserRole.FIELD_WORKER)


@pytest_asyncio.fixture
async def field_worker_with_access(app, db_establishment):
    """Create a field worker with an APPROVED relation to db_establishment."""
    from app.db.database import AsyncSessionLocal
    from app.domain.establishment import UserEstablishmentStatus
    from app.domain.user import UserStatus
    from app.models.user import User
    from app.models.user import UserRole as ORMUserRole
    from app.models.user_establishment import UserEstablishment

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Maria",
                last_name="Field Worker",
                email=f"{user_id}@test.com",
                role=ORMUserRole.FIELD_WORKER,
                status=UserStatus.ACTIVE,
            )
        )
        session.add(
            UserEstablishment(
                user_id=user_id,
                establishment_id=db_establishment.id,
                status=UserEstablishmentStatus.APPROVED,
            )
        )
        await session.commit()

    token = create_access_token(user_id, role=UserRole.FIELD_WORKER)
    return {"Authorization": f"Bearer {token}"}, user_id


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

    async def test_edit_appends_audit_row(
        self, client, db_establishment, admin_user
    ):
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
