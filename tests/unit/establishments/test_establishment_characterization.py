import pytest
from pydantic import ValidationError

from app.domain.establishment_characterization import (
    CharacterizationStatus,
    characterization_status,
)
from app.schemas.establishments.establishment_characterization_schema import (
    EstablishmentCharacterization,
)


def _invalid_fields(payload: dict) -> set:
    """Validate ``payload`` and return the top-level fields that failed."""
    with pytest.raises(ValidationError) as exc_info:
        EstablishmentCharacterization.model_validate(payload)
    return {error["loc"][0] for error in exc_info.value.errors()}


class TestCharacterizationStatus:
    @pytest.mark.parametrize(
        "characterization",
        [
            None,
            {},
            EstablishmentCharacterization().model_dump(mode="json"),
            {"district": "", "meals": [], "daily_attendance": None},
        ],
    )
    def test_profile_without_answers_is_pending(self, characterization):
        """A missing profile, or one holding only null, blank or empty values,
        is pending."""
        assert (
            characterization_status(characterization) == CharacterizationStatus.PENDING
        )

    @pytest.mark.parametrize(
        "answer",
        [{"meals": ["lunch"]}, {"district": "Comuna 3"}, {"cooks_per_service": 0}],
    )
    def test_profile_with_one_answer_is_complete(self, answer):
        """A single answered field, including a zero count, makes it complete."""
        characterization = {
            **EstablishmentCharacterization().model_dump(mode="json"),
            **answer,
        }

        assert (
            characterization_status(characterization) == CharacterizationStatus.COMPLETE
        )


class TestOtherText:
    @pytest.mark.parametrize(
        "payload",
        [
            {"care_tasks": ["food_assistance", "other"], "care_tasks_other": "Ropero"},
            {"premises": "other", "premises_other": "Club"},
        ],
    )
    def test_accepted_when_other_is_chosen(self, payload):
        """Other text is kept when "other" is chosen, in a multiple or single
        choice field."""
        profile = EstablishmentCharacterization.model_validate(payload)

        other_field = next(key for key in payload if key.endswith("_other"))
        assert getattr(profile, other_field) == payload[other_field]

    @pytest.mark.parametrize(
        "payload",
        [
            {"care_tasks": ["food_assistance"], "care_tasks_other": "Ropero"},
            {"premises": "lent_space", "premises_other": "Club"},
            {"premises_other": "Club"},
        ],
    )
    def test_rejected_without_other_chosen_naming_the_other_field(self, payload):
        """Other text without "other" chosen fails on the ``*_other`` field."""
        other_field = next(key for key in payload if key.endswith("_other"))

        assert _invalid_fields(payload) == {other_field}

    def test_blank_other_text_without_other_is_accepted_as_null(self):
        """A blank other text counts as unanswered, so it needs no "other"."""
        profile = EstablishmentCharacterization.model_validate({"premises_other": ""})

        assert profile.premises_other is None


class TestFieldRules:
    @pytest.mark.parametrize(
        "payload",
        [
            {"premises": "castle"},
            {"space_types": ["community_kitchen", "spaceship"]},
            {"meals": ["lunch", "lunch"]},
            {"district": "x" * 101},
            {"contact_phone": "11-4567-ABCD"},
            {"contact_phone": "1" * 31},
            {"contact_email": "not-an-email"},
            {"daily_attendance": -1},
            {"daily_attendance": 100_001},
            {"cooks_per_service": 1_001},
        ],
    )
    def test_invalid_value_fails_on_its_field(self, payload):
        """Values outside the options, repeated, too long or out of range fail
        on the field that holds them."""
        assert _invalid_fields(payload) == set(payload)

    def test_blank_strings_are_read_as_null(self):
        """Blank text and email are stored as unanswered."""
        profile = EstablishmentCharacterization.model_validate(
            {"district": "", "contact_email": "  "}
        )

        assert profile.district is None
        assert profile.contact_email is None

    def test_null_list_is_read_as_empty(self):
        """A null multiple choice field is stored as unanswered."""
        profile = EstablishmentCharacterization.model_validate({"meals": None})

        assert profile.meals == []


class TestOpeningHours:
    def test_valid_slots_are_kept(self):
        """Several slots with different days and times are accepted."""
        slots = [
            {
                "days": ["monday", "tuesday"],
                "opens_at": "11:30",
                "closes_at": "14:30",
            },
            {"days": ["saturday"], "opens_at": "16:00", "closes_at": "18:00"},
        ]

        profile = EstablishmentCharacterization.model_validate({"opening_hours": slots})

        assert profile.model_dump(mode="json")["opening_hours"] == slots

    @pytest.mark.parametrize(
        "slot",
        [
            {"days": [], "opens_at": "11:00", "closes_at": "12:00"},
            {"days": ["monday", "monday"], "opens_at": "11:00", "closes_at": "12:00"},
            {"days": ["funday"], "opens_at": "11:00", "closes_at": "12:00"},
            {"days": ["monday"], "opens_at": "24:00", "closes_at": "23:00"},
            {"days": ["monday"], "opens_at": "9:00", "closes_at": "12:00"},
            {"days": ["monday"], "opens_at": "12:00", "closes_at": "12:00"},
            # Slots crossing midnight are not supported.
            {"days": ["friday"], "opens_at": "22:00", "closes_at": "01:00"},
        ],
    )
    def test_invalid_slot_fails_on_opening_hours(self, slot):
        """A slot with no or repeated days, a malformed time, or closing at or
        before opening fails on ``opening_hours``."""
        assert _invalid_fields({"opening_hours": [slot]}) == {"opening_hours"}
