import uuid

from fastapi import status

from tests.integration.helpers import responses_url
from tests.integration.surveys.responses.helpers import (
    NOW,
    _create_survey,
    _make_establishment,
    _response_body,
    _valid_answers,
)
from tests.integration.urls import SURVEYS_URL

ANALYTICS_URL = "/api/v1/analytics"


class TestGetDashboardDetail:
    async def test_shows_question_text_and_resolved_option_label(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        answers = _valid_answers(survey)
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(survey["id"], answers),
                headers=headers,
            )
        ).json()

        response = await client.get(
            responses_url(created["survey_id"], created["id"], "detail"),
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=headers,
            )
        ).json()

        response = await client.get(
            responses_url(created["survey_id"], created["id"], "detail"),
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=fw_headers,
            )
        ).json()

        response = await client.get(
            responses_url(created["survey_id"], created["id"], "detail"),
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_response_not_found_returns_404(self, client, admin_user):
        headers, _ = admin_user
        response = await client.get(
            responses_url(uuid.uuid4()),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestFiesScoring:
    @staticmethod
    def _fies_survey_body(name: str) -> dict:
        from app.reference_data.fies_template import build_fies_template

        template = build_fies_template()
        return {
            "name": name,
            "description": template.description,
            "response_target": template.response_target.value,
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
            responses_url(survey["id"]),
            json=_response_body(survey["id"], answers),
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
            responses_url(survey["id"]),
            json=_response_body(survey["id"], answers),
            headers=headers,
        )
        assert response.json()["score_fies"] == 8

    async def test_custom_survey_response_has_null_score(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)  # default instrument_type=custom
        response = await client.post(
            responses_url(survey["id"]),
            json=_response_body(survey["id"], _valid_answers(survey)),
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], original_answers),
                headers=headers,
            )
        ).json()
        assert created["score_fies"] == 0

        new_answers = {
            q["id"]: q["options"][0]["id"] for q in survey["questions"]
        }  # all "Sí"
        edited = (
            await client.put(
                responses_url(created["survey_id"], created["id"]),
                json={
                    "answers": new_answers,
                    "response_number": created["response_number"],
                    "event_at": NOW,
                },
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
            responses_url(survey["id"]),
            json=_response_body(survey["id"], answers),
            headers=headers,
        )

        list_response = await client.get(responses_url(survey["id"]), headers=headers)
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], answers),
                headers=headers,
            )
        ).json()

        detail = await client.get(
            responses_url(created["survey_id"], created["id"]),
            headers=headers,
        )
        assert detail.json()["score_fies"] == 5


class TestSurveyResponseSummary:
    async def test_counts_all_responses_with_no_filters(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"], _valid_answers(survey), event_at="2024-01-01T00:00:00Z"
            ),
            headers=headers,
        )
        await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                id=str(uuid.uuid4()),
                event_at="2024-06-01T00:00:00Z",
            ),
            headers=headers,
        )

        url = f"{ANALYTICS_URL}/survey-response-summary"
        response = await client.get(url, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["response_count"] == 2
        # Anonymous responses have no establishment, so the distinct count is
        # legitimately zero — the metric only means something for
        # establishment-targeted surveys.
        assert body["participating_establishments_count"] == 0
        assert body["last_event_at"] == "2024-06-01T00:00:00Z"

    async def test_counts_distinct_establishments(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        other = await _make_establishment(place_id="place-indicators-001")
        survey = await _create_survey(client, headers, response_target="establishment")

        for establishment_id in (db_establishment.id, other.id):
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    establishment_id=str(establishment_id),
                ),
                headers=headers,
            )

        url = f"{ANALYTICS_URL}/survey-response-summary"
        response = await client.get(url, headers=headers)

        assert response.json()["participating_establishments_count"] == 2

    async def test_filters_by_survey_id(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey_a = await _create_survey(client, headers, name="Encuesta A")
        survey_b = await _create_survey(client, headers, name="Encuesta B")
        await client.post(
            responses_url(survey_a["id"]),
            json=_response_body(survey_a["id"], _valid_answers(survey_a)),
            headers=headers,
        )
        await client.post(
            responses_url(survey_b["id"]),
            json=_response_body(survey_b["id"], _valid_answers(survey_b)),
            headers=headers,
        )

        response = await client.get(
            f"{ANALYTICS_URL}/survey-response-summary",
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
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"], _valid_answers(survey), event_at="2024-01-01T00:00:00Z"
            ),
            headers=headers,
        )
        await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                id=str(uuid.uuid4()),
                event_at="2024-06-15T00:00:00Z",
            ),
            headers=headers,
        )

        response = await client.get(
            f"{ANALYTICS_URL}/survey-response-summary",
            params={"event_at_from": "2024-05-01T00:00:00Z"},
            headers=headers,
        )

        body = response.json()
        assert body["response_count"] == 1
        assert body["last_event_at"] == "2024-06-15T00:00:00Z"

    async def test_filters_by_city(self, client, db_establishment, admin_user):
        """The global summary keeps its establishment join, so a location
        filter there simply matches only establishment-linked responses."""
        headers, _ = admin_user
        cordoba = await _make_establishment(place_id="place-indicators-002")
        survey = await _create_survey(client, headers, response_target="establishment")
        for establishment_id in (db_establishment.id, cordoba.id):
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    establishment_id=str(establishment_id),
                ),
                headers=headers,
            )

        response = await client.get(
            f"{ANALYTICS_URL}/survey-response-summary",
            params={"city": "Buenos Aires"},
            headers=headers,
        )

        assert response.json()["response_count"] == 1

    async def test_no_responses_returns_zero_and_null_last_event_at(
        self, client, admin_user
    ):
        headers, _ = admin_user
        url = f"{ANALYTICS_URL}/survey-response-summary"
        response = await client.get(url, headers=headers)

        body = response.json()
        assert body["response_count"] == 0
        assert body["participating_establishments_count"] == 0
        assert body["last_event_at"] is None

    async def test_invalid_date_range_returns_400(self, client, admin_user):
        headers, _ = admin_user
        response = await client.get(
            f"{ANALYTICS_URL}/survey-response-summary",
            params={
                "event_at_from": "2024-06-01T00:00:00Z",
                "event_at_to": "2024-01-01T00:00:00Z",
            },
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_field_worker_forbidden(self, client, field_worker_without_access):
        headers, _ = field_worker_without_access
        url = f"{ANALYTICS_URL}/survey-response-summary"
        response = await client.get(url, headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_allowed(self, client, analyst_user):
        headers, _ = analyst_user
        url = f"{ANALYTICS_URL}/survey-response-summary"
        response = await client.get(url, headers=headers)
        assert response.status_code == status.HTTP_200_OK

    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"{ANALYTICS_URL}/survey-response-summary")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
