import uuid

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import func, select

from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

SURVEYS_URL = "/api/v1/surveys"


@pytest_asyncio.fixture
async def admin_author(make_user_with_role):
    return await make_user_with_role(UserRole.ADMIN)


@pytest_asyncio.fixture
async def analyst_author(make_user_with_role):
    return await make_user_with_role(UserRole.ANALYST)


def _survey_body(
    name: str = "Encuesta A",
    response_target: str = "anonymous",
    questions=None,
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
        "response_target": response_target,
        "questions": questions,
    }


def _survey_update_body(**overrides):
    """Build a complete PUT payload with an explicit numbering policy."""
    requires_response_number = overrides.pop("requires_response_number", False)
    body = _survey_body(**overrides)
    body["requires_response_number"] = requires_response_number
    return body


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
        assert body["response_target"] == "anonymous"
        assert body["requires_response_number"] is None
        assert body["is_active"] is True
        assert body["created_by_id"] == str(user_id)
        assert [q["position"] for q in body["questions"]] == [0, 1]
        first = body["questions"][0]
        assert first["response_type"] == "single_choice"
        assert [o["text"] for o in first["options"]] == ["Sí", "No"]

    @pytest.mark.parametrize("setting", [True, False])
    async def test_response_number_setting_round_trips(
        self, client, admin_author, setting
    ):
        headers, _ = admin_author
        body = _survey_body(name=f"Number setting {setting}")
        body["requires_response_number"] = setting

        created = await client.post(SURVEYS_URL, json=body, headers=headers)
        fetched = await client.get(
            f"{SURVEYS_URL}/{created.json()['id']}", headers=headers
        )

        assert created.status_code == status.HTTP_201_CREATED
        assert created.json()["requires_response_number"] is setting
        assert fetched.json()["requires_response_number"] is setting

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

    @pytest.mark.parametrize("target", ["subject", "establishment", "anonymous"])
    async def test_every_response_target_round_trips(
        self, client, admin_author, target
    ):
        headers, _ = admin_author
        response = await _create(
            client, headers, name=f"Encuesta {target}", response_target=target
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["response_target"] == target

    async def test_missing_response_target_returns_422(self, client, admin_author):
        headers, _ = admin_author
        body = _survey_body()
        del body["response_target"]
        response = await client.post(SURVEYS_URL, json=body, headers=headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_scope_and_establishment_ids_are_gone(self, client, admin_author):
        headers, _ = admin_author
        body = (await _create(client, headers)).json()
        assert "scope" not in body
        assert "establishment_ids" not in body


class TestGetFieldWorkerAccess:
    """A field worker may fetch full survey detail (needed to render the
    response form) for any active survey. Establishment-based gating is gone;
    `is_active` is the only visibility rule left."""

    @pytest.mark.parametrize("target", ["subject", "establishment", "anonymous"])
    async def test_any_active_survey_succeeds(
        self, client, admin_author, field_worker_headers, target
    ):
        admin_headers, _ = admin_author
        survey_id = (
            await _create(
                client,
                admin_headers,
                name=f"Encuesta {target}",
                response_target=target,
            )
        ).json()["id"]
        response = await client.get(
            f"{SURVEYS_URL}/{survey_id}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["questions"][0]["text"] == "¿Comió hoy?"

    async def test_missing_survey_returns_404(self, client, field_worker_headers):
        response = await client.get(
            f"{SURVEYS_URL}/{uuid.uuid4()}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_inactive_survey_returns_403(
        self, client, admin_author, field_worker_headers
    ):
        admin_headers, _ = admin_author
        survey_id = (await _create(client, admin_headers)).json()["id"]
        await client.patch(
            f"{SURVEYS_URL}/{survey_id}/status",
            json={"is_active": False},
            headers=admin_headers,
        )
        response = await client.get(
            f"{SURVEYS_URL}/{survey_id}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestAvailableSurveys:
    """`/available` no longer filters by establishment: a field worker with no
    establishments at all sees every active survey."""

    async def test_unattached_field_worker_sees_all_active_surveys(
        self, client, admin_author, field_worker_headers
    ):
        admin_headers, _ = admin_author
        for target in ("subject", "establishment", "anonymous"):
            await _create(
                client,
                admin_headers,
                name=f"Encuesta {target}",
                response_target=target,
            )

        response = await client.get(
            f"{SURVEYS_URL}/available", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 3
        assert {item["response_target"] for item in body["items"]} == {
            "subject",
            "establishment",
            "anonymous",
        }

    async def test_inactive_surveys_are_excluded(
        self, client, admin_author, field_worker_headers
    ):
        admin_headers, _ = admin_author
        survey_id = (await _create(client, admin_headers)).json()["id"]
        await client.patch(
            f"{SURVEYS_URL}/{survey_id}/status",
            json={"is_active": False},
            headers=admin_headers,
        )
        response = await client.get(
            f"{SURVEYS_URL}/available", headers=field_worker_headers
        )
        assert response.json()["total"] == 0

    async def test_admin_can_fetch_inactive_survey(self, client, admin_author):
        admin_headers, _ = admin_author
        survey_id = (await _create(client, admin_headers)).json()["id"]
        await client.patch(
            f"{SURVEYS_URL}/{survey_id}/status",
            json={"is_active": False},
            headers=admin_headers,
        )
        response = await client.get(f"{SURVEYS_URL}/{survey_id}", headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK


class TestUpdate:
    async def test_reconcile_insert_update_delete(self, client, admin_author):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]  # single_choice question, keep by id
        # Rename the survey (changes a surveys column -> exercises updated_at onupdate),
        # rename the kept question, drop the second, add a new numeric question.
        payload = _survey_update_body(
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
        payload = _survey_update_body(
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
            f"{SURVEYS_URL}/{survey_id}",
            json=_survey_update_body(),
            headers=analyst_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestLockedAfterResponses:
    async def test_effective_response_number_setting_is_locked(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        create_body = _survey_body(name="Locked number policy")
        create_body["requires_response_number"] = True
        created_response = await client.post(
            SURVEYS_URL, json=create_body, headers=headers
        )
        created = created_response.json()
        first = created["questions"][0]
        submitted = await client.post(
            f"{SURVEYS_URL}/{created['id']}/responses",
            json={
                "answers": {first["id"]: first["options"][0]["id"]},
                "response_number": 1,
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        update_body = _survey_update_body(
            name=created["name"], questions=created["questions"]
        )
        update_body["requires_response_number"] = False

        updated = await client.put(
            f"{SURVEYS_URL}/{created['id']}", json=update_body, headers=headers
        )

        assert submitted.status_code == status.HTTP_201_CREATED
        assert updated.status_code == status.HTTP_409_CONFLICT

    async def test_delete_question_after_response_returns_409(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]

        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {keep["id"]: keep["options"][0]["id"]},
                "response_number": 1,
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        # Drop the second question entirely -> structural deletion, locked.
        payload = _survey_update_body(
            questions=[
                {
                    "id": keep["id"],
                    "text": keep["text"],
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": keep["options"][0]["id"], "text": "Sí"},
                        {"id": keep["options"][1]["id"], "text": "No"},
                    ],
                }
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.parametrize(
        "picked_option_index,expected_status",
        [(0, status.HTTP_200_OK), (2, status.HTTP_409_CONFLICT)],
        ids=["unreferenced_option_removed", "referenced_option_removed"],
    )
    async def test_remove_option_after_response(
        self,
        client,
        admin_author,
        db_establishment,
        picked_option_index,
        expected_status,
    ):
        headers, _ = admin_author
        created = (
            await _create(
                client,
                headers,
                questions=[
                    {
                        "text": "¿Comió hoy?",
                        "response_type": "single_choice",
                        "is_required": True,
                        "options": [
                            {"text": "Sí"},
                            {"text": "No"},
                            {"text": "No sabe"},
                        ],
                    }
                ],
            )
        ).json()
        survey_id = created["id"]
        question = created["questions"][0]
        si_option, no_option, _ = question["options"]
        picked_option = question["options"][picked_option_index]

        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {question["id"]: picked_option["id"]},
                "response_number": 1,
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        # Always try to drop "No sabe" (index 2); only referenced when picked.
        payload = _survey_update_body(
            questions=[
                {
                    "id": question["id"],
                    "text": question["text"],
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": si_option["id"], "text": "Sí"},
                        {"id": no_option["id"], "text": "No"},
                    ],
                }
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == expected_status
        if expected_status == status.HTTP_200_OK:
            remaining = response.json()["questions"][0]["options"]
            remaining_ids = {o["id"] for o in remaining}
            assert remaining_ids == {si_option["id"], no_option["id"]}

    async def test_rename_question_after_response_succeeds(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]
        second = created["questions"][1]

        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {keep["id"]: keep["options"][0]["id"]},
                "response_number": 1,
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        # Rename the kept question and leave the rest structurally identical.
        payload = _survey_update_body(
            questions=[
                {
                    "id": keep["id"],
                    "text": "¿Comió bien hoy? (renombrada)",
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": keep["options"][0]["id"], "text": "Sí"},
                        {"id": keep["options"][1]["id"], "text": "No"},
                    ],
                },
                {
                    "id": second["id"],
                    "text": second["text"],
                    "response_type": "text",
                    "is_required": False,
                    "options": [],
                },
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert (
            response.json()["questions"][0]["text"] == "¿Comió bien hoy? (renombrada)"
        )

    async def test_add_optional_question_after_response_succeeds(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]
        second = created["questions"][1]

        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {keep["id"]: keep["options"][0]["id"]},
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        # Keep both existing questions untouched, add a new optional one.
        payload = _survey_update_body(
            questions=[
                {
                    "id": keep["id"],
                    "text": keep["text"],
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": keep["options"][0]["id"], "text": "Sí"},
                        {"id": keep["options"][1]["id"], "text": "No"},
                    ],
                },
                {
                    "id": second["id"],
                    "text": second["text"],
                    "response_type": "text",
                    "is_required": False,
                    "options": [],
                },
                {
                    "text": "¿Cuántas personas viven en el hogar?",
                    "response_type": "numeric",
                    "is_required": False,
                    "options": [],
                },
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [q["text"] for q in body["questions"]] == [
            keep["text"],
            second["text"],
            "¿Cuántas personas viven en el hogar?",
        ]
        assert body["questions"][2]["is_required"] is False

    async def test_add_required_question_with_foreign_id_returns_409(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]
        second = created["questions"][1]

        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {keep["id"]: keep["options"][0]["id"]},
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        # A required "new" question posing as existing via a foreign id must
        # still be rejected, not slip past the lock check.
        payload = _survey_update_body(
            questions=[
                {
                    "id": keep["id"],
                    "text": keep["text"],
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": keep["options"][0]["id"], "text": "Sí"},
                        {"id": keep["options"][1]["id"], "text": "No"},
                    ],
                },
                {
                    "id": second["id"],
                    "text": second["text"],
                    "response_type": "text",
                    "is_required": False,
                    "options": [],
                },
                {
                    "id": str(uuid.uuid4()),
                    "text": "¿Cuántas personas viven en el hogar?",
                    "response_type": "numeric",
                    "is_required": True,
                    "options": [],
                },
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_add_required_question_after_response_returns_409(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        created = (await _create(client, headers)).json()
        survey_id = created["id"]
        keep = created["questions"][0]
        second = created["questions"][1]

        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {keep["id"]: keep["options"][0]["id"]},
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        # Keep both existing questions untouched, add a new required one.
        payload = _survey_update_body(
            questions=[
                {
                    "id": keep["id"],
                    "text": keep["text"],
                    "response_type": "single_choice",
                    "is_required": True,
                    "options": [
                        {"id": keep["options"][0]["id"], "text": "Sí"},
                        {"id": keep["options"][1]["id"], "text": "No"},
                    ],
                },
                {
                    "id": second["id"],
                    "text": second["text"],
                    "response_type": "text",
                    "is_required": False,
                    "options": [],
                },
                {
                    "text": "¿Cuántas personas viven en el hogar?",
                    "response_type": "numeric",
                    "is_required": True,
                    "options": [],
                },
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_remove_option_referenced_in_multiple_choice_returns_409(
        self, client, admin_author, db_establishment
    ):
        headers, _ = admin_author
        created = (
            await _create(
                client,
                headers,
                questions=[
                    {
                        "text": "¿Qué alimentos consumió?",
                        "response_type": "multiple_choice",
                        "is_required": True,
                        "options": [
                            {"text": "Verduras"},
                            {"text": "Frutas"},
                            {"text": "Lácteos"},
                        ],
                    }
                ],
            )
        ).json()
        survey_id = created["id"]
        question = created["questions"][0]
        verduras, frutas, lacteos = question["options"]

        # Picked as one of two options inside the MULTIPLE_CHOICE list.
        submit = await client.post(
            f"{SURVEYS_URL}/{survey_id}/responses",
            json={
                "answers": {question["id"]: [verduras["id"], lacteos["id"]]},
                "response_number": 1,
                "event_at": "2024-06-01T12:00:00Z",
            },
            headers=headers,
        )
        assert submit.status_code == status.HTTP_201_CREATED

        payload = _survey_update_body(
            questions=[
                {
                    "id": question["id"],
                    "text": question["text"],
                    "response_type": "multiple_choice",
                    "is_required": True,
                    "options": [
                        {"id": verduras["id"], "text": "Verduras"},
                        {"id": frutas["id"], "text": "Frutas"},
                    ],
                }
            ]
        )
        response = await client.put(
            f"{SURVEYS_URL}/{survey_id}", json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_409_CONFLICT


class TestDuplicate:
    @pytest.mark.parametrize("setting", [True, False, None])
    async def test_duplicate_inherits_response_number_setting(
        self, client, admin_author, setting
    ):
        headers, _ = admin_author
        body = _survey_body(name=f"Source {setting}")
        if setting is not None:
            body["requires_response_number"] = setting
        original = await client.post(SURVEYS_URL, json=body, headers=headers)

        duplicate = await client.post(
            f"{SURVEYS_URL}/{original.json()['id']}/duplicate", headers=headers
        )

        assert duplicate.json()["requires_response_number"] is setting

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
        from app.models.surveys.survey_question import SurveyQuestion
        from app.models.surveys.survey_question_option import (
            SurveyQuestionOption,
        )

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
        assert body["requires_response_number"] is True
        assert body["name"] == ""
        assert "12 meses" in body["description"]
        assert len(body["questions"]) == 8
        for question in body["questions"]:
            assert question["response_type"] == "single_choice"
            assert question["is_required"] is True
            assert [o["text"] for o in question["options"]] == ["Sí", "No"]
        assert [q["position"] for q in body["questions"]] == list(range(8))
