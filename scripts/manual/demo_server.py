"""Local capture server with explicit demonstration doubles for external services.

The real backend still handles authentication, validation, nutrition calculations,
catalog matching, transactions and persistence. These doubles do not validate
Gemini quality or object-storage integration. Use only with a disposable E2E database.
"""

import json
import os
from pathlib import Path

from app.config.settings import settings
from app.core.dependencies import get_llm_client, get_receipt_intake_service
from app.core.interfaces.llm_client import ILlmClient
from app.core.interfaces.object_storage import IObjectStorage
from app.db.unit_of_work import UnitOfWork
from app.main import app
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService

if settings.environment.lower() not in {"test", "e2e"}:
    raise RuntimeError("Demonstration services require ENVIRONMENT=test or e2e")


class DemonstrationModel(ILlmClient):
    async def complete(
        self, *, prompt, response_schema, image=None, image_content_type=None
    ):
        if image is not None:
            return {
                "lines": [
                    {
                        "description": "Arroz blanco, crudo",
                        "raw_quantity": 2,
                        "raw_unit_text": "kg",
                    }
                ]
            }
        context = json.loads(prompt.split("Context:\n")[1])
        if "recipes" not in context:
            rice = next(
                (f for f in context["stock"] if "Arroz blanco" in f["name"]),
                context["stock"][0],
            )
            return {
                "cultural_dish_viable": False,
                "candidates": [
                    {
                        "concept": "Arroz para el comedor",
                        "food_ids": [rice["food_id"]],
                        "cultural_identity": None,
                    }
                ],
            }
        return {
            "recipes": [
                {
                    "proposal_id": r["id"],
                    "name": r["name"],
                    "steps": [
                        {
                            "text": "Cocinar el arroz hasta que esté tierno y servir.",
                            "food_ids": [i["food_id"] for i in r["ingredients"]],
                        }
                    ],
                    "cultural_identity": r["cultural_identity"],
                }
                for r in context["recipes"]
            ]
        }


class DemonstrationStorage(IObjectStorage):
    async def save(self, *, key, content_type, data):
        output = (
            Path(os.environ.get("MANUAL_OBJECT_DIRECTORY", "../receipt-objects")) / key
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)


model = DemonstrationModel()


async def receipt_service():
    async with UnitOfWork() as uow:
        yield ReceiptIntakeService(
            uow, DemonstrationStorage(), FoodIntakeService(uow), model
        )


app.dependency_overrides[get_llm_client] = lambda: model
app.dependency_overrides[get_receipt_intake_service] = receipt_service
