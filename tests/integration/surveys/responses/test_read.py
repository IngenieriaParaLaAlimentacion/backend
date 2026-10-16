import uuid

import pytest
from fastapi import status

from tests.integration.helpers import responses_url
from tests.integration.surveys.responses.helpers import (
    _create_survey,
    _make_establishment,
    _make_subject,
    _response_body,
    _valid_answers,
)
from tests.integration.urls import SURVEYS_URL


class TestGetResponse:
    """The full-detail view a mobile client hits after tapping a `/me/activity`
    entry, since the activity feed only carries a summary."""

    async def test_missing_response_returns_404(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        response = await client.get(
            responses_url(survey["id"], uuid.uuid4()), headers=headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_response_of_another_survey_returns_404(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        other_survey = await _create_survey(client, headers, name="Encuesta B")
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=headers,
            )
        ).json()

        response = await client.get(
            responses_url(other_survey["id"], created["id"]), headers=headers
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], answers),
                headers=fw_headers,
            )
        ).json()
        response = await client.get(
            responses_url(created["survey_id"], created["id"]), headers=fw_headers
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=admin_headers,
            )
        ).json()
        response = await client.get(
            responses_url(created["survey_id"], created["id"]), headers=fw_headers
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=fw_headers,
            )
        ).json()
        response = await client.get(
            responses_url(created["survey_id"], created["id"]), headers=admin_headers
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
                responses_url(survey["id"]),
                json=_response_body(survey["id"], _valid_answers(survey)),
                headers=admin_headers,
            )
        ).json()
        response = await client.get(
            responses_url(created["survey_id"], created["id"]), headers=analyst_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestListAvailable:
    """Availability stopped being establishment-scoped: every role sees every
    active survey, whatever its response target."""

    async def test_items_expose_response_target(
        self, client, admin_user, field_worker_without_access
    ):
        """Mobile routes on this before opening the form, so it must be on the
        list item and not only on the detail."""
        admin_headers, _ = admin_user
        fw_headers, _ = field_worker_without_access
        await _create_survey(
            client, admin_headers, name="Subject Survey", response_target="subject"
        )
        response = await client.get(f"{SURVEYS_URL}/available", headers=fw_headers)
        assert response.json()["items"][0]["response_target"] == "subject"

    async def test_analyst_allowed(self, client, analyst_user):
        headers, _ = analyst_user
        response = await client.get(f"{SURVEYS_URL}/available", headers=headers)
        assert response.status_code == status.HTTP_200_OK


class TestListBySurvey:
    async def test_shows_submitter_establishment_and_date(
        self, client, db_establishment, admin_user, field_worker_with_access
    ):
        admin_headers, _ = admin_user
        fw_headers, fw_id = field_worker_with_access
        survey = await _create_survey(
            client, admin_headers, response_target="establishment"
        )
        created = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    establishment_id=str(db_establishment.id),
                ),
                headers=fw_headers,
            )
        ).json()

        response = await client.get(
            responses_url(survey["id"]),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["id"] == created["id"]
        assert item["survey"]["id"] == survey["id"]
        assert item["establishment"]["id"] == str(db_establishment.id)
        assert item["subject"] is None
        assert item["submitted_by"]["id"] == str(fw_id)
        assert "event_at" in item

    async def test_orders_by_event_at_desc(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        older = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    event_at="2024-06-01T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()
        newer = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    id=str(uuid.uuid4()),
                    event_at="2024-06-05T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()

        response = await client.get(
            responses_url(survey["id"]),
            headers=headers,
        )

        ids = [item["id"] for item in response.json()["items"]]
        assert ids == [newer["id"], older["id"]]

    @pytest.mark.parametrize(
        "sort_order,oldest_first",
        [
            ("event_at_asc", True),
            ("event_at_desc", False),
            ("created_at_asc", True),
            ("created_at_desc", False),
        ],
    )
    async def test_sort_order(
        self, client, db_establishment, admin_user, sort_order, oldest_first
    ):
        """Responses are created oldest event_at first, so creation order and
        event_at order agree — one expectation covers both sort columns."""
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        created = []
        for event_at in ("2024-06-01T00:00:00Z", "2024-06-05T00:00:00Z"):
            created.append(
                (
                    await client.post(
                        responses_url(survey["id"]),
                        json=_response_body(
                            survey["id"],
                            _valid_answers(survey),
                            id=str(uuid.uuid4()),
                            event_at=event_at,
                        ),
                        headers=headers,
                    )
                ).json()
            )

        response = await client.get(
            responses_url(survey["id"]),
            params={"sort_order": sort_order},
            headers=headers,
        )

        ids = [item["id"] for item in response.json()["items"]]
        expected = [row["id"] for row in created]
        assert ids == (expected if oldest_first else expected[::-1])

    async def test_rejects_unknown_sort_order(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)

        response = await client.get(
            responses_url(survey["id"]),
            params={"sort_order": "subject_name_asc"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_rejects_inverted_event_at_range(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)

        response = await client.get(
            responses_url(survey["id"]),
            params={
                "event_at_from": "2024-06-05T00:00:00Z",
                "event_at_to": "2024-06-01T00:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_paginates(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        for _ in range(3):
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"], _valid_answers(survey), id=str(uuid.uuid4())
                ),
                headers=headers,
            )

        response = await client.get(
            responses_url(survey["id"]),
            params={"page": 1, "page_size": 2},
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
            responses_url(survey_a["id"]),
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
            responses_url(survey["id"]),
            headers=fw_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_allowed(self, client, admin_user, analyst_user):
        admin_headers, _ = admin_user
        analyst_headers, _ = analyst_user
        survey = await _create_survey(client, admin_headers)

        response = await client.get(
            responses_url(survey["id"]),
            headers=analyst_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_unknown_survey_returns_404(self, client, admin_user):
        headers, _ = admin_user

        unknown_id = str(uuid.uuid4())
        response = await client.get(
            responses_url(unknown_id),
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unauthenticated_returns_401(self, client, admin_user):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)

        response = await client.get(responses_url(survey["id"]))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestListFilters:
    """Geographic and establishment filters only make sense for
    establishment-targeted surveys, so these all build one."""

    @staticmethod
    async def _survey_with_two_establishments(client, headers, db_establishment, other):
        survey = await _create_survey(client, headers, response_target="establishment")
        for establishment_id in (db_establishment.id, other.id):
            response = await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    establishment_id=str(establishment_id),
                ),
                headers=headers,
            )
            assert response.status_code == status.HTTP_201_CREATED
        return survey

    async def test_filters_by_establishment(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        other = await _make_establishment(place_id="place-filter-001")
        survey = await self._survey_with_two_establishments(
            client, headers, db_establishment, other
        )

        response = await client.get(
            responses_url(survey["id"]),
            params={
                "establishment_id": str(db_establishment.id),
                "page": 1,
                "page_size": 10,
            },
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["establishment"]["id"] == str(db_establishment.id)

    async def test_filters_by_subject(self, client, admin_user, db_subject):
        headers, _ = admin_user
        other = await _make_subject()
        survey = await _create_survey(client, headers, response_target="subject")
        for subject_id in (db_subject.id, other.id):
            created = await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    id=str(uuid.uuid4()),
                    subject_id=str(subject_id),
                ),
                headers=headers,
            )
            assert created.status_code == status.HTTP_201_CREATED

        response = await client.get(
            responses_url(survey["id"]),
            params={"subject_id": str(db_subject.id)},
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["subject"]["id"] == str(db_subject.id)

    @pytest.mark.parametrize("target", ["establishment", "anonymous"])
    async def test_subject_filter_on_non_subject_survey_returns_400(
        self, client, admin_user, db_subject, target
    ):
        """Mirror of the establishment case: ``subject_id`` is null on every
        response to a survey not targeted at subjects."""
        headers, _ = admin_user
        survey = await _create_survey(
            client, headers, response_target=target, name=f"Encuesta sujeto {target}"
        )
        response = await client.get(
            responses_url(survey["id"]),
            params={"subject_id": str(db_subject.id)},
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("target", ["subject", "anonymous"])
    @pytest.mark.parametrize("field", ["city", "province"])
    async def test_location_filter_on_non_establishment_survey_returns_400(
        self, client, admin_user, target, field
    ):
        """Those responses carry no establishment, so the join would silently
        drop them — an empty page reads as "no data", not "wrong filter"."""
        headers, _ = admin_user
        survey = await _create_survey(
            client, headers, response_target=target, name=f"Encuesta {target}"
        )
        response = await client.get(
            responses_url(survey["id"]),
            params={field: "Cordoba"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_filters_by_event_at_range(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        old = (
            await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    event_at="2024-01-01T00:00:00Z",
                ),
                headers=headers,
            )
        ).json()
        recent = (
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
        ).json()

        response = await client.get(
            responses_url(survey["id"]),
            params={
                "survey_id": survey["id"],
                "event_at_from": "2024-05-01T00:00:00Z",
            },
            headers=headers,
        )
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == [recent["id"]]
        assert old["id"] not in ids

    async def test_response_number_exact_and_range_filters_include_duplicates(
        self, client, db_establishment, admin_user
    ):
        """Number filters return every response sharing the requested number."""
        headers, _ = admin_user
        survey = await _create_survey(client, headers)
        responses = []
        for response_number in (74, 74, 75):
            response = await client.post(
                responses_url(survey["id"]),
                json=_response_body(
                    survey["id"],
                    _valid_answers(survey),
                    response_number=response_number,
                ),
                headers=headers,
            )
            assert response.status_code == status.HTTP_201_CREATED
            responses.append(response.json())

        exact = await client.get(
            responses_url(survey["id"]),
            params={"response_number": 74},
            headers=headers,
        )
        assert exact.status_code == status.HTTP_200_OK
        assert {item["id"] for item in exact.json()["items"]} == {
            responses[0]["id"],
            responses[1]["id"],
        }

        ranged = await client.get(
            responses_url(survey["id"]),
            params={"response_number_from": 74, "response_number_to": 75},
            headers=headers,
        )
        assert ranged.status_code == status.HTTP_200_OK
        assert {item["id"] for item in ranged.json()["items"]} == {
            item["id"] for item in responses
        }

    async def test_filters_by_city(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        cordoba = await _make_establishment(place_id="place-filter-002")
        survey = await self._survey_with_two_establishments(
            client, headers, db_establishment, cordoba
        )

        response = await client.get(
            responses_url(survey["id"]),
            params={"city": "Buenos Aires"},
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["establishment"]["city"] == "Buenos Aires"

    async def test_filters_by_province(self, client, db_establishment, admin_user):
        headers, _ = admin_user
        cordoba = await _make_establishment(place_id="place-filter-003")
        survey = await self._survey_with_two_establishments(
            client, headers, db_establishment, cordoba
        )

        response = await client.get(
            responses_url(survey["id"]),
            params={"province": "Cordoba"},
            headers=headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["establishment"]["province"] == "Cordoba"

    async def test_city_filter_case_insensitive(
        self, client, db_establishment, admin_user
    ):
        headers, _ = admin_user
        survey = await _create_survey(client, headers, response_target="establishment")
        await client.post(
            responses_url(survey["id"]),
            json=_response_body(
                survey["id"],
                _valid_answers(survey),
                establishment_id=str(db_establishment.id),
            ),
            headers=headers,
        )

        response = await client.get(
            responses_url(survey["id"]),
            params={"city": "buenos aires"},  # lowercase
            headers=headers,
        )
        assert response.json()["total"] == 1
