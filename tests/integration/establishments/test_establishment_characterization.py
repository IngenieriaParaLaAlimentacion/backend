import uuid

import pytest
from fastapi import status

from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole
from tests.integration.urls import CHARACTERIZATION_URL, DASHBOARD_URL

FULL_PROFILE = {
    "district": "Comuna 3",
    "neighborhood": "Balvanera",
    "cross_streets": "Uriburu y Azcuénaga",
    "contact_phone": "11 4567-8901",
    "contact_email": "comedor.norte@example.com",
    "opening_hours": [
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "opens_at": "11:30",
            "closes_at": "14:30",
        },
        {"days": ["saturday"], "opens_at": "16:00", "closes_at": "18:00"},
    ],
    "space_types": ["community_kitchen", "school_support"],
    "space_types_other": None,
    "care_tasks": ["food_assistance", "school_support", "other"],
    "care_tasks_other": "Ropero comunitario",
    "premises": "lent_space",
    "premises_other": None,
    "bathroom": "exclusive",
    "bathroom_other": None,
    "utilities": ["running_water", "electricity", "gas_cylinder", "sewer"],
    "affiliations": ["social_movement", "local_government"],
    "affiliations_other": None,
    "daily_attendance": 85,
    "attendee_ages": ["early_childhood", "children", "adults"],
    "meals": ["lunch", "snack"],
    "service_types": ["on_site", "takeaway"],
    "service_types_other": None,
    "food_reception_frequency": "weekly",
    "cooks_per_service": 4,
    "kitchen_equipment": ["stove", "fridge", "large_pots"],
    "kitchen_equipment_other": None,
    "cultural_identities": [],
    "cultural_identities_other": None,
}


def _url(establishment_id) -> str:
    return CHARACTERIZATION_URL.format(establishment_id=establishment_id)


class TestReplaceCharacterization:
    async def test_full_profile_is_stored_and_read_from_the_dashboard(
        self, client, db_establishment, admin_headers
    ):
        """The saved profile is returned as stored, and the dashboard and
        detail read it back."""
        response = await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "characterization_status": "complete",
            "characterization": FULL_PROFILE,
        }
        dashboard = (
            await client.get(
                DASHBOARD_URL.format(establishment_id=db_establishment.id),
                headers=admin_headers,
            )
        ).json()
        assert dashboard["characterization"] == FULL_PROFILE
        assert dashboard["establishment"]["characterization_status"] == "complete"

    async def test_replace_clears_fields_left_out(
        self, client, db_establishment, admin_headers
    ):
        """Saving replaces the whole profile, so fields not sent are cleared."""
        await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=admin_headers
        )

        response = await client.put(
            _url(db_establishment.id),
            json={"meals": ["dinner"], "district": None},
            headers=admin_headers,
        )

        profile = response.json()["characterization"]
        assert profile["meals"] == ["dinner"]
        assert profile["district"] is None
        assert profile["care_tasks"] == []

    async def test_empty_profile_returns_to_pending(
        self, client, db_establishment, admin_headers
    ):
        """Clearing every field leaves the profile pending, and a status sent
        in the body is ignored."""
        await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=admin_headers
        )

        response = await client.put(
            _url(db_establishment.id),
            json={"characterization_status": "complete", "district": ""},
            headers=admin_headers,
        )

        assert response.json()["characterization_status"] == "pending"
        detail = await client.get(
            f"/api/v1/establishments/{db_establishment.id}", headers=admin_headers
        )
        assert detail.json()["characterization_status"] == "pending"

    async def test_unknown_establishment_returns_404(self, client, admin_headers):
        response = await client.put(
            _url(uuid.uuid4()), json=FULL_PROFILE, headers=admin_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["type"] == "/errors/establishment-not-found"


class TestCharacterizationPermissions:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPERADMIN])
    async def test_admins_can_edit_any_establishment(
        self, client, db_establishment, make_user_with_role, role
    ):
        headers, _ = await make_user_with_role(role)

        response = await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_field_worker_with_approved_access_can_edit(
        self, client, field_worker_with_access, db_establishment
    ):
        headers, _ = field_worker_with_access

        response = await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.parametrize(
        "relation_status",
        [
            UserEstablishmentStatus.PENDING,
            UserEstablishmentStatus.REJECTED,
            UserEstablishmentStatus.REVOKED,
            UserEstablishmentStatus.WITHDRAWN,
        ],
    )
    async def test_field_worker_without_approved_access_returns_403(
        self,
        client,
        db_establishment,
        make_field_worker_with_access,
        relation_status,
    ):
        headers, _ = await make_field_worker_with_access(
            db_establishment.id, relation_status
        )

        response = await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_returns_403(
        self, client, db_establishment, make_user_with_role
    ):
        """Analysts may read the profile but not edit it."""
        headers, _ = await make_user_with_role(UserRole.ANALYST)

        response = await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_rejected_edit_leaves_the_profile_unchanged(
        self, client, db_establishment, admin_headers, make_user_with_role
    ):
        await client.put(
            _url(db_establishment.id), json=FULL_PROFILE, headers=admin_headers
        )
        analyst_headers, _ = await make_user_with_role(UserRole.ANALYST)

        await client.put(_url(db_establishment.id), json={}, headers=analyst_headers)

        dashboard = await client.get(
            DASHBOARD_URL.format(establishment_id=db_establishment.id),
            headers=admin_headers,
        )
        assert dashboard.json()["characterization"] == FULL_PROFILE


class TestCharacterizationValidation:
    @pytest.mark.parametrize(
        ("payload", "field"),
        [
            ({"premises": "castle"}, "premises"),
            ({"premises": "lent_space", "premises_other": "Club"}, "premises_other"),
            ({"meals": ["lunch", "lunch"]}, "meals"),
            (
                {
                    "opening_hours": [
                        {"days": ["monday"], "opens_at": "14:00", "closes_at": "11:00"}
                    ]
                },
                "opening_hours",
            ),
        ],
    )
    async def test_invalid_profile_returns_422_naming_the_field(
        self, client, db_establishment, admin_headers, payload, field
    ):
        response = await client.put(
            _url(db_establishment.id), json=payload, headers=admin_headers
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        body = response.json()
        assert body["type"] == "/errors/validation-failed"
        assert body["field"] == field

    async def test_invalid_value_is_not_echoed(
        self, client, db_establishment, admin_headers
    ):
        """The 422 names the field but never repeats what was sent."""
        response = await client.put(
            _url(db_establishment.id),
            json={"contact_email": "secret-not-an-email"},
            headers=admin_headers,
        )

        assert response.json()["field"] == "contact_email"
        assert "secret-not-an-email" not in response.text
