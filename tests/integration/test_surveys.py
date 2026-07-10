import uuid

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

SURVEYS_URL = "/api/v1/surveys"


async def _make_author(role: UserRole = UserRole.ADMIN):
    """Create a real DB user and return (headers, user_id) for that author."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserStatus
    from app.models.user import User
    from app.models.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Author",
                last_name=role.value.title(),
                email=f"{user_id}@test.com",
                role=ORMUserRole(role.value),
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    token = create_access_token(user_id, role=role)
    return {"Authorization": f"Bearer {token}"}, user_id


@pytest_asyncio.fixture
async def admin_author(app):
    return await _make_author(UserRole.ADMIN)


@pytest_asyncio.fixture
async def analyst_author(app):
    return await _make_author(UserRole.ANALYST)


def _survey_body(
    name: str = "Encuesta A",
    scope: str = "generic",
    questions=None,
    establishment_ids=None,
    description=None,
):
    if questions is None:
        questions = [
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
        ]
    return {
        "name": name,
        "description": description,
        "scope": scope,
        "questions": questions,
        "establishment_ids": establishment_ids or [],
    }


async def _create(client, headers, **overrides):
    return await client.post(
        SURVEYS_URL, json=_survey_body(**overrides), headers=headers
    )


class TestAuth:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(SURVEYS_URL, json=_survey_body())
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_forbidden(self, client, field_worker_headers):
        response = await client.post(
            SURVEYS_URL, json=_survey_body(), headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_field_worker_forbidden_on_list(self, client, field_worker_headers):
        response = await client.get(SURVEYS_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestCreateAndGet:
    async def test_create_returns_full_config(self, client, admin_author):
        headers, user_id = admin_author
        response = await _create(client, headers)
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["name"] == "Encuesta A"
        assert body["scope"] == "generic"
        assert body["is_active"] is True
        assert body["created_by_id"] == str(user_id)
        assert [q["position"] for q in body["questions"]] == [0, 1]
        first = body["questions"][0]
        assert first["response_type"] == "single_choice"
        assert [o["text"] for o in first["options"]] == ["Sí", "No"]

    async def test_get_returns_questions_in_order(self, client, admin_author):
        headers, _ = admin_author
        survey_id = (await _create(client, headers)).json()["id"]
        response = await client.get(f"{SURVEYS_URL}/{survey_id}", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["questions"][0]["text"] == "¿Comió hoy?"
        assert body["questions"][1]["text"] == "Comentarios"

    async def test_get_missing_returns_404(self, client, admin_author):
        headers, _ = admin_author
        response = await client.get(f"{SURVEYS_URL}/{uuid.uuid4()}", headers=headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/problem+json")

    async def test_case_insensitive_name_conflict_returns_409(
        self, client, admin_author
    ):
        headers, _ = admin_author
        await _create(client, headers, name="Encuesta Única")
        response = await _create(client, headers, name="encuesta única")
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_invalid_structure_returns_400(self, client, admin_author):
        headers, _ = admin_author
        # single_choice with a single option is invalid.
        bad = [
            {
                "text": "¿Sí o sí?",
                "response_type": "single_choice",
                "is_required": True,
                "options": [{"text": "Sí"}],
            }
        ]
        response = await _create(client, headers, questions=bad)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_targeted_unknown_establishment_returns_404(
        self, client, admin_author
    ):
        headers, _ = admin_author
        response = await _create(
            client,
            headers,
            scope="targeted",
            establishment_ids=[str(uuid.uuid4())],
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_targeted_with_establishment_succeeds(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        response = await _create(
            client,
            headers,
            scope="targeted",
            establishment_ids=[str(db_establishment.id)],
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["establishment_ids"] == [str(db_establishment.id)]


class TestUpdate:
    async def test_reconcile_insert_update_delete(self, client, admin_author):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]  # single_choice question, keep by id
        # Rename the survey (changes a surveys column -> exercises updated_at onupdate),
        # rename the kept question, drop the second, add a new numeric question.
        payload = _survey_body(
            name="Encuesta A renombrada",
            questions=[
                {
                    "id": keep["id"],
                    "text": "¿Comió bien hoy?",
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": keep["options"][0]["id"], "text": "Sí"},
                        {"text": "No"},
                    ],
                },
                {
                    "text": "¿Cuántas comidas?",
                    "response_type": "numeric",
                    "is_required": False,
                    "options": [],
                },
            ],
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "Encuesta A renombrada"
        assert body["questions"][0]["id"] == keep["id"]
        assert body["questions"][0]["text"] == "¿Comió bien hoy?"
        assert body["questions"][1]["text"] == "¿Cuántas comidas?"
        assert body["questions"][1]["response_type"] == "numeric"

    async def test_reconcile_foreign_question_id_returns_400(
        self, client, admin_author
    ):
        headers, _ = admin_author
        survey_id = (await _create(client, headers)).json()["id"]
        payload = _survey_body(
            questions=[
                {
                    "id": str(uuid.uuid4()),
                    "text": "No es mía",
                    "response_type": "text",
                    "is_required": False,
                    "options": [],
                }
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_analyst_cannot_edit_others_survey(
        self, client, admin_author, analyst_author
    ):
        admin_headers, _ = admin_author
        analyst_headers, _ = analyst_author
        survey_id = (await _create(client, admin_headers)).json()["id"]
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=_survey_body(), headers=analyst_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestDuplicate:
    async def test_duplicate_suffixes_name(self, client, admin_author):
        headers, _ = admin_author
        survey_id = (await _create(client, headers, name="Base")).json()["id"]

        first = await client.post(
            f"{SURVEYS_URL}/{survey_id}/duplicate", headers=headers
        )
        assert first.status_code == status.HTTP_201_CREATED
        assert first.json()["name"] == "Base (copy)"

        second = await client.post(
            f"{SURVEYS_URL}/{survey_id}/duplicate", headers=headers
        )
        assert second.json()["name"] == "Base (copy 2)"

    async def test_duplicate_copies_questions_with_new_ids(self, client, admin_author):
        headers, _ = admin_author
        original = (await _create(client, headers, name="Original")).json()
        copy = (
            await client.post(
                f"{SURVEYS_URL}/{original['id']}/duplicate", headers=headers
            )
        ).json()
        assert copy["id"] != original["id"]
        original_qids = {q["id"] for q in original["questions"]}
        copy_qids = {q["id"] for q in copy["questions"]}
        assert original_qids.isdisjoint(copy_qids)
        assert [q["text"] for q in copy["questions"]] == [
            q["text"] for q in original["questions"]
        ]

    async def test_duplicate_inherits_inactive_state(self, client, admin_author):
        headers, _ = admin_author
        survey_id = (await _create(client, headers, name="Paused")).json()["id"]
        await client.patch(
            f"{SURVEYS_URL}/{survey_id}/status",
            json={"is_active": False},
            headers=headers,
        )

        copy = await client.post(
            f"{SURVEYS_URL}/{survey_id}/duplicate", headers=headers
        )
        assert copy.status_code == status.HTTP_201_CREATED
        assert copy.json()["is_active"] is False


class TestDeleteCascade:
    async def test_delete_removes_survey_and_children(self, client, admin_author):
        from app.db.database import AsyncSessionLocal
        from app.models.survey_question import SurveyQuestion
        from app.models.survey_question_option import SurveyQuestionOption

        headers, _ = admin_author
        survey_id = (await _create(client, headers)).json()["id"]

        response = await client.delete(f"{SURVEYS_URL}/{survey_id}", headers=headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        get_response = await client.get(f"{SURVEYS_URL}/{survey_id}", headers=headers)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

        async with AsyncSessionLocal() as session:
            questions = await session.execute(
                select(func.count()).select_from(SurveyQuestion)
            )
            options = await session.execute(
                select(func.count()).select_from(SurveyQuestionOption)
            )
            assert questions.scalar_one() == 0
            assert options.scalar_one() == 0


class TestStatusToggle:
    async def test_deactivate_then_reflected_in_get(self, client, admin_author):
        headers, _ = admin_author
        survey_id = (await _create(client, headers)).json()["id"]

        response = await client.patch(
            f"{SURVEYS_URL}/{survey_id}/status",
            json={"is_active": False},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_active"] is False

        get_response = await client.get(f"{SURVEYS_URL}/{survey_id}", headers=headers)
        assert get_response.json()["is_active"] is False


class TestListing:
    async def test_filters_and_pagination(self, client, admin_author, analyst_author):
        admin_headers, _ = admin_author
        analyst_headers, analyst_id = analyst_author

        await _create(client, admin_headers, name="Alpha generic")
        await _create(client, admin_headers, name="Beta inactive", description="x")
        await _create(client, analyst_headers, name="Gamma by analyst")

        # Name search.
        search = await client.get(
            SURVEYS_URL, params={"search": "alpha"}, headers=admin_headers
        )
        assert search.status_code == status.HTTP_200_OK
        assert [s["name"] for s in search.json()["items"]] == ["Alpha generic"]

        # created_by filter.
        by_analyst = await client.get(
            SURVEYS_URL, params={"created_by": str(analyst_id)}, headers=admin_headers
        )
        assert [s["name"] for s in by_analyst.json()["items"]] == ["Gamma by analyst"]

        # Pagination metadata.
        page = await client.get(
            SURVEYS_URL, params={"page": 1, "page_size": 2}, headers=admin_headers
        )
        body = page.json()
        assert body["total"] == 3
        assert body["total_pages"] == 2
        assert len(body["items"]) == 2

    async def test_is_active_filter(self, client, admin_author):
        headers, _ = admin_author
        survey_id = (await _create(client, headers, name="Toggleable")).json()["id"]
        await client.patch(
            f"{SURVEYS_URL}/{survey_id}/status",
            json={"is_active": False},
            headers=headers,
        )
        active = await client.get(
            SURVEYS_URL, params={"is_active": True}, headers=headers
        )
        assert active.json()["total"] == 0
        inactive = await client.get(
            SURVEYS_URL, params={"is_active": False}, headers=headers
        )
        assert inactive.json()["total"] == 1

    async def test_sort_by_name_asc(self, client, admin_author):
        headers, _ = admin_author
        await _create(client, headers, name="Zeta")
        await _create(client, headers, name="Alfa")
        response = await client.get(
            SURVEYS_URL, params={"sort_order": "name_asc"}, headers=headers
        )
        assert [s["name"] for s in response.json()["items"]] == ["Alfa", "Zeta"]


class TestFiesTemplate:
    async def test_returns_eight_item_structure(self, client, admin_author):
        headers, _ = admin_author
        response = await client.get(f"{SURVEYS_URL}/templates/fies", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == ""
        assert "12 meses" in body["description"]
        assert len(body["questions"]) == 8
        for question in body["questions"]:
            assert question["response_type"] == "single_choice"
            assert question["is_required"] is True
            assert [o["text"] for o in question["options"]] == ["Sí", "No"]
        assert [q["position"] for q in body["questions"]] == list(range(8))
