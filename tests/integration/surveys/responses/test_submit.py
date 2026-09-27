import uuid

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import func, select

from app.domain.user import UserRole
from tests.integration.helpers import responses_url
from tests.integration.surveys.responses.helpers import (
    _create_survey,
    _make_establishment,
    _make_subject,
    _response_body,
    _valid_answers,
)
from tests.integration.urls import SURVEYS_URL


@pytest_asyncio.fixture
async def superadmin_user(make_user_with_role):
    return await make_user_with_role(UserRole.SUPERADMIN)


class TestSubmitAuth:
    async def test_unauthenticated_returns_401(self, client, db_establishment):
        response = await client.post(
            responses_url(uuid.uuid4()),
            json=_response_body(uuid.uuid4(), {}),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_analyst_forbidden(self, client, db_establishment, analyst_user):
        headers, _ = analyst_user
        response = await client.post(
            responses_url(uuid.uuid4()),
            json=_response_body(uuid.uuid4(), {}),
            headers=headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSubmitRoleMatrix:
    async def test_field_worker_without_any_establishment_succeeds(
        self, client, db_establishment, admin_user, field_worker_without_access
    ):
        """Previously 403. The establishment on a response is data, not
        permission, so a field worker who signed up purely to answer surveys —
        with no establishment relation at all — can submit."""
        admin_headers, _ = admin_user
        fw_headers, fw_id = field_worker_without_access
        survey = await _create_survey(client, admin_headers)
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["submitted_by_id"] == str(fw_id)

    async def test_field_worker_may_answer_for_an_unrelated_establishment(
        self, client, db_establishment, admin_user, field_worker_without_access
    ):
        """No approved relation is required to name an establishment."""
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_without_access
        survey = await _create_survey(
            client, admin_headers, response_target="establishment"
        )
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                establishment_id=str(db_establishment.id),
            ),
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["establishment_id"] == str(db_establishment.id)

    async def test_admin_succeeds(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
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
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
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
            responses_url(survey["id"]),
            json=_response_body(survey["id"], {}),
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_unknown_survey_returns_404(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        response = await client.post(
            responses_url(uuid.uuid4()),
            json=_response_body(uuid.uuid4(), {}),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unknown_establishment_returns_404(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="establishment")
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                establishment_id=str(uuid.uuid4()),
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unknown_subject_returns_404(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="subject")
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                subject_id=str(uuid.uuid4()),
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "target,field",
        [
            ("subject", "establishment_id"),
            ("establishment", "subject_id"),
            ("anonymous", "subject_id"),
            ("anonymous", "establishment_id"),
        ],
    )
    async def test_wrong_entity_for_target_returns_400(
        self, client, db_establishment, admin_user, target, field
    ):
        headers, _ = admin_user
        survey = await _create_survey(
            client, headers, response_target=target, name=f"Encuesta {target}"
        )
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"], _valid_answers(survey), **{field: str(uuid.uuid4())}
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("target", ["subject", "establishment"])
    async def test_missing_required_entity_returns_400(
        self, client, admin_user, target
    ):
        headers, _ = admin_user
        survey = await _create_survey(
            client, headers, response_target=target, name=f"Encuesta {target}"
        )
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
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
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"], {question["id"]: [{"not": "a valid option id"}]}
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_future_event_at_returns_422(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"], _valid_answers(survey), event_at="2099-01-01T00:00:00Z"
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_subject_targeted_submission_succeeds(
        self, client, admin_user, db_subject
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="subject")
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                subject_id=str(db_subject.id),
            ),
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["subject_id"] == str(db_subject.id)
        assert body["establishment_id"] is None

    async def test_anonymous_submission_carries_no_target(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["subject_id"] is None
        assert body["establishment_id"] is None


class TestTargetUniqueness:
    """A subject, and an establishment, answer a given survey once. Anonymous
    surveys stay unbounded."""

    async def test_second_response_for_same_subject_returns_409(
        self, client, admin_user, db_subject
    ):
        headers, user_id = admin_user
        survey = await _create_survey(client, headers, response_target="subject")
        body = _response_body(
            survey["id"], _valid_answers(survey), subject_id=str(db_subject.id)
        )
        first = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.headers["content-type"].startswith("application/problem+json")
        existing = second.json()["existing_response"]
        assert existing["id"] == first.json()["id"]
        assert existing["submitted_by"]["id"] == str(user_id)
        assert existing["event_at"] is not None

    async def test_second_response_for_same_establishment_returns_409(
        self, client, admin_user, db_establishment
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="establishment")
        body = _response_body(
            survey["id"],
            _valid_answers(survey),
            establishment_id=str(db_establishment.id),
        )
        first = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert second.status_code == status.HTTP_409_CONFLICT

    async def test_anonymous_survey_accepts_many_responses(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        for _ in range(3):
            response = await client.post(
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=headers,
            )
            assert response.status_code == status.HTTP_201_CREATED

    async def test_required_survey_rejects_missing_number(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, requires_response_number=True)
        body = _response_body(survey["id"], _valid_answers(survey))
        del body["response_number"]

        response = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"].endswith("/errors/invalid-survey-response")

    @pytest.mark.parametrize("setting", [False, None])
    async def test_optional_survey_persists_null_number(
        self, client, admin_user, setting
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, requires_response_number=setting)
        body = _response_body(
            survey["id"], _valid_answers(survey), response_number=None
        )

        response = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["response_number"] is None

    async def test_anonymous_responses_may_share_a_response_number(
        self, client, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        body = _response_body(survey["id"], _valid_answers(survey), response_number=1)

        first = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        second = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert first.json()["response_number"] == second.json()["response_number"] == 1

    @pytest.mark.parametrize("target", ["subject", "establishment"])
    async def test_targeted_responses_may_share_a_number_when_targets_differ(
        self, client, admin_user, db_establishment, db_subject, target
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target=target)
        if target == "subject":
            other_target = await _make_subject(dni=33444556)
            target_key = "subject_id"
            target_ids = (db_subject.id, other_target.id)
        else:
            other_target = await _make_establishment(place_id="place-test-003")
            target_key = "establishment_id"
            target_ids = (db_establishment.id, other_target.id)

        for target_id in target_ids:
            response = await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    response_number=1,
                    **{target_key: str(target_id)},
                ),
                headers=headers,
            )
            assert response.status_code == status.HTTP_201_CREATED

    async def test_same_subject_may_answer_a_different_survey(
        self, client, admin_user, db_subject
    ):
        headers, _ = admin_user
        first_survey = await _create_survey(
            client, headers, name="Encuesta 1", response_target="subject"
        )
        second_survey = await _create_survey(
            client, headers, name="Encuesta 2", response_target="subject"
        )
        for survey in (first_survey, second_survey):
            response = await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    subject_id=str(db_subject.id),
                ),
                headers=headers,
            )
            assert response.status_code == status.HTTP_201_CREATED

    async def test_replayed_id_wins_over_uniqueness(
        self, client, admin_user, db_subject
    ):
        """Id-first ordering: a retried sync gets its own response back with a
        200, not a conflict blaming it for its own earlier submission."""
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="subject")
        client_id = str(uuid.uuid4())
        body = _response_body(
            survey["id"],
            _valid_answers(survey),
            subject_id=str(db_subject.id),
            id=client_id,
        )
        first = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert first.status_code == status.HTTP_201_CREATED

        replay = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert replay.status_code == status.HTTP_200_OK
        assert replay.json()["id"] == client_id

    async def test_conflict_survives_without_the_service_pre_check(
        self, client, admin_user, db_subject, monkeypatch
    ):
        """The partial unique indexes, not the pre-check, are the real
        guarantee. With the pre-check blinded — as it is in a genuine race —
        the repository must still recognise which index Postgres rejected the
        insert on, or the collision is mislabelled as an id replay and escapes
        as a 500 instead of this 409.
        """
        from app.repositories.surveys.survey_response_repository import (
            SurveyResponseRepository,
        )

        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="subject")
        body = _response_body(
            survey["id"], _valid_answers(survey), subject_id=str(db_subject.id)
        )
        first = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert first.status_code == status.HTTP_201_CREATED

        real_get_by_target = SurveyResponseRepository.get_by_target
        calls = {"n": 0}

        async def blind_first_call(self, *args, **kwargs):
            """Return None once — the pre-check's view of a lost race — then
            behave normally so the post-INSERT lookup can name the winner."""
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_get_by_target(self, *args, **kwargs)

        monkeypatch.setattr(SurveyResponseRepository, "get_by_target", blind_first_call)

        second = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["existing_response"]["id"] == first.json()["id"]

    async def test_id_replayed_under_a_different_survey_returns_400(
        self, client, admin_user
    ):
        """One client id belongs to one survey. Reusing it elsewhere would hand
        back the first survey's answers as a 200."""
        headers, _ = admin_user
        first_survey = await _create_survey(client, headers, name="Encuesta 1")
        second_survey = await _create_survey(client, headers, name="Encuesta 2")
        client_id = str(uuid.uuid4())

        created = await client.post(
            responses_url(first_survey["id"]),
            json=_response_body(
                first_survey["id"], _valid_answers(first_survey), id=client_id
            ),
            headers=headers,
        )
        assert created.status_code == status.HTTP_201_CREATED

        crossed = await client.post(
            responses_url(second_survey["id"]),
            json=_response_body(
                second_survey["id"], _valid_answers(second_survey), id=client_id
            ),
            headers=headers,
        )
        assert crossed.status_code == status.HTTP_400_BAD_REQUEST


class TestSubmitIdempotentReplay:
    async def test_same_client_id_replays_without_duplicate_row(
        self, client, db_establishment, admin_user
    ):
        from app.models.surveys.survey_response import SurveyResponse

        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response_id = str(uuid.uuid4())
        body = _response_body(survey["id"], _valid_answers(survey), id=response_id)

        first = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = await client.post(
            responses_url(survey["id"]), json=body, headers=headers
        )
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
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
            headers=headers,
        )
        get_response = await client.get(
            f"{SURVEYS_URL}/{survey['id']}", headers=headers
        )
        assert get_response.json()["response_count"] == 1
