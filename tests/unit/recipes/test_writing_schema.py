"""Provider decoding stays simple while backend output bounds remain enforced."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.recipes.recipe_schema import WritingBatch
from app.services.recipes.generation import writing_response_schema


def test_wire_schema_omits_nested_bounds_but_retains_required_fields_and_enums():
    schema = writing_response_schema()
    assert schema["required"] == ["recipes"]
    recipe = schema["$defs"]["RecipeWriting"]
    step = schema["$defs"]["PreparationStep"]
    assert recipe["required"] == ["proposal_id", "name", "steps"]
    assert step["required"] == ["text", "food_ids"]
    assert "maxItems" not in recipe["properties"]["steps"]
    assert "maxItems" not in step["properties"]["food_ids"]
    assert schema["$defs"]["CulturalIdentity"]["enum"]
    assert (
        WritingBatch.model_json_schema()["$defs"]["RecipeWriting"]["properties"][
            "steps"
        ]["maxItems"]
        == 30
    )


@pytest.mark.parametrize(
    "invalid", ["long_text", "too_many_steps", "too_many_ids", "bad_uuid"]
)
def test_local_schema_keeps_validation_bounds(invalid):
    recipe = {
        "proposal_id": str(uuid4()),
        "name": "Receta",
        "steps": [{"text": "Servir.", "food_ids": [str(uuid4())]}],
    }
    if invalid == "long_text":
        recipe["steps"][0]["text"] = "x" * 1501
    elif invalid == "too_many_steps":
        recipe["steps"] *= 31
    elif invalid == "too_many_ids":
        recipe["steps"][0]["food_ids"] *= 51
    else:
        recipe["proposal_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        WritingBatch.model_validate({"recipes": [recipe, recipe]})
