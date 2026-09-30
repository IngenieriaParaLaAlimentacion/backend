import uuid

from fastapi import status
from sqlalchemy import func, select

from app.domain.establishment import UserEstablishmentStatus
from tests.integration.helpers import responses_url
from tests.integration.surveys.responses.helpers import (
    NOW,
    _create_survey,
    _link_user,
    _response_body,
    _valid_answers,
)


class TestEdit:
    async def test_optional_edit_clears_live_and_audit_number(
        self, client, db_establishment, admin_user
    ):
        from app.db.database import AsyncSessionLocal
        from app.models.surveys.survey_response import SurveyResponse
        from app.models.surveys.survey_response_edit import SurveyResponseEdit

        headers, _ = admin_user
        survey = await _create_survey(client, headers, requires_response_number=False)
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"], _valid_answers(survey), response_number=12
                ),
                headers=headers,
            )
        ).json()

        edited = await client.put(
            responses_url(survey["id"], created["id"]),
            json={"answers": _valid_answers(survey), "event_at": NOW},
            headers=headers,
        )

        assert edited.status_code == status.HTTP_200_OK
        assert edited.json()["response_number"] is None
        async with AsyncSessionLocal() as session:
            live = await session.get(SurveyResponse, uuid.UUID(created["id"]))
            audit = await session.scalar(
                select(SurveyResponseEdit).where(
                    SurveyResponseEdit.response_id == uuid.UUID(created["id"])
                )
            )
        assert live.response_number is None
        assert audit.response_number is None

    async def test_required_edit_without_number_creates_no_audit(
        self, client, db_establishment, admin_user
    ):
        from app.db.database import AsyncSessionLocal
        from app.models.surveys.survey_response_edit import SurveyResponseEdit

        headers, _ = admin_user
        survey = await _create_survey(client, headers, requires_response_number=True)
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=headers,
            )
        ).json()

        edited = await client.put(
            responses_url(survey["id"], created["id"]),
            json={"answers": _valid_answers(survey), "event_at": NOW},
            headers=headers,
        )

        assert edited.status_code == status.HTTP_400_BAD_REQUEST
        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count()).select_from(SurveyResponseEdit)
            )
        assert count == 0

    async def test_missing_response_returns_404(self, client, admin_user):
        headers, _ = admin_user
        response = await client.put(
            responses_url(uuid.uuid4(), uuid.uuid4()),
            json={"answers": {}, "response_number": 1, "event_at": NOW},
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=admin_headers,
            )
        ).json()
        response = await client.put(
            responses_url(created["survey_id"], created["id"]),
            json={
                "answers": _valid_answers(survey),
                "response_number": created["response_number"],
                "event_at": NOW,
            },
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=fw_headers,
            )
        ).json()
        question = survey["questions"][0]
        new_answers = {question["id"]: question["options"][1]["id"]}
        response = await client.put(
            responses_url(created["survey_id"], created["id"]),
            json={
                "answers": new_answers,
                "response_number": created["response_number"],
                "event_at": NOW,
            },
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=fw_headers,
            )
        ).json()
        response = await client.put(
            responses_url(created["survey_id"], created["id"]),
            json={
                "answers": _valid_answers(survey),
                "response_number": created["response_number"],
                "event_at": NOW,
            },
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_edit_appends_audit_row(self, client, db_establishment, admin_user):
        from app.models.surveys.survey_response_edit import SurveyResponseEdit

        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=headers,
            )
        ).json()
        await client.put(
            responses_url(created["survey_id"], created["id"]),
            json={
                "answers": _valid_answers(survey),
                "response_number": created["response_number"],
                "event_at": NOW,
            },
            headers=headers,
        )

        from app.db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            count = await session.execute(
                select(func.count()).select_from(SurveyResponseEdit)
            )
            assert count.scalar_one() == 1

    async def test_edit_to_a_used_number_succeeds_and_preserves_audit_snapshot(
        self, client, db_establishment, admin_user
    ):
        from app.db.database import AsyncSessionLocal
        from app.models.surveys.survey_response_edit import SurveyResponseEdit

        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        answers = _valid_answers(survey)
        first = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], answers, response_number=1),
            headers=headers,
        )
        second = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], answers, response_number=2),
            headers=headers,
        )
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED

        edited = await client.put(
            responses_url(survey["id"], second.json()["id"]),
            json={
                "answers": answers,
                "response_number": 1,
                "event_at": NOW,
            },
            headers=headers,
        )

        assert edited.status_code == status.HTTP_200_OK
        assert edited.json()["response_number"] == 1
        async with AsyncSessionLocal() as session:
            audit = await session.scalar(
                select(SurveyResponseEdit).where(
                    SurveyResponseEdit.response_id == uuid.UUID(second.json()["id"])
                )
            )
        assert audit is not None
        assert audit.response_number == 1

    async def test_last_write_wins_older_event_at_does_not_overwrite(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        original_answers = _valid_answers(survey)
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"], original_answers, event_at="2024-06-02T00:00:00Z"
                ),
                headers=headers,
            )
        ).json()
        question = survey["questions"][0]
        older_answers = {question["id"]: question["options"][1]["id"]}

        response = await client.put(
            responses_url(created["survey_id"], created["id"]),
            json={
                "answers": older_answers,
                "response_number": created["response_number"],
                "event_at": "2024-06-01T00:00:00Z",
            },
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        # The edit is logged, but the response's current state is unchanged
        # since its event_at is more recent than the edit's.
        assert response.json()["answers"] == original_answers

        from app.db.database import AsyncSessionLocal
        from app.models.surveys.survey_response_edit import SurveyResponseEdit

        async with AsyncSessionLocal() as session:
            count = await session.execute(
                select(func.count()).select_from(SurveyResponseEdit)
            )
            assert count.scalar_one() == 1


class TestEditAnalyst:
    async def test_analyst_loses_edit_once_link_is_withdrawn(
        self, client, db_establishment, admin_user, analyst_user
    ):
        """An approved analyst edits their own response like a field
        worker, and stops being able to once the link is withdrawn."""
        from app.db.database import AsyncSessionLocal
        from app.models.auth.user_establishment import UserEstablishment

        admin_headers, _ = admin_user
        analyst_headers, analyst_id = analyst_user
        await _link_user(
            analyst_id, db_establishment.id, UserEstablishmentStatus.APPROVED
        )
        survey = await _create_survey(
            client, admin_headers, response_target="establishment"
        )
        body = _response_body(
            survey["id"],
            _valid_answers(survey),
            establishment_id=str(db_establishment.id),
        )
        created = (
            await client.post(
                responses_url(survey["id"]), json=body, headers=analyst_headers
            )
        ).json()
        edit_url = responses_url(survey["id"], created["id"])
        edit_body = {
            "answers": _valid_answers(survey),
            "response_number": 1,
            "event_at": NOW,
        }

        edited = await client.put(edit_url, json=edit_body, headers=analyst_headers)
        assert edited.status_code == status.HTTP_200_OK

        async with AsyncSessionLocal() as session:
            relation = await session.scalar(
                select(UserEstablishment).where(UserEstablishment.user_id == analyst_id)
            )
            relation.status = UserEstablishmentStatus.WITHDRAWN
            await session.commit()

        denied = await client.put(edit_url, json=edit_body, headers=analyst_headers)
        assert denied.status_code == status.HTTP_403_FORBIDDEN
