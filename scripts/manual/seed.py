"""Extend the shared E2E reference dataset with manual-only survey modalities.

Requires backend PR #219 (seed_reference_e2e.py). Run from that backend checkout
with its dependencies and PYTHONPATH. Credentials in the output are disposable
E2E credentials; never commit the generated fixture.
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx

from app.config.settings import settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument(
        "--public-api-url", help="API URL used by host-side verification"
    )
    args = parser.parse_args()
    if settings.environment.lower() not in {"test", "e2e"}:
        raise SystemExit("Manual fixtures require ENVIRONMENT=test or e2e")
    try:
        from app.reference_data.reference_e2e_dataset import (
            ESTABLISHMENT_REQUESTS,
            ESTABLISHMENTS,
            FIES_SURVEY_NAME,
            PASSWORD,
            SUBJECTS,
            USERS,
            reference_id,
        )
        from seed_reference_e2e import seed_reference_e2e

        from seed_superadmin import create_super_admin
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Use a backend checkout containing PR #219 (reference E2E seed)"
        ) from error

    await create_super_admin()
    await seed_reference_e2e()
    users = {user.key: user for user in USERS}
    accounts = {
        "superadmin": {
            "email": settings.seed_admin_email,
            "password": settings.seed_admin_password,
        },
        **{
            role: {
                "email": users[key].email,
                "password": PASSWORD,
                "name": users[key].name,
            }
            for role, key in [
                ("admin", "admin"),
                ("analyst", "analyst"),
                ("field_worker", "field_worker_1"),
            ]
        },
    }
    async with httpx.AsyncClient(base_url=args.api_url, timeout=60) as client:
        tokens = {}

        async def call(method, path, payload=None, role="superadmin", **params):
            response = await client.request(
                method,
                path,
                json=payload,
                headers={"Authorization": f"Bearer {tokens[role]}"}
                if role in tokens
                else {},
                params=params,
            )
            response.raise_for_status()
            return response.json() if response.content else None

        for role, account in accounts.items():
            result = await call(
                "POST",
                "/auth/login",
                {
                    "email": account["email"],
                    "password": account["password"],
                    "device_id": str(uuid4()),
                },
                role=role,
            )
            tokens[role] = result["access_token"]
        spec = next(e for e in ESTABLISHMENTS if e.key == "caba")
        establishments = (await call("GET", "/establishments", page_size=100))["items"]
        establishment = next(
            e for e in establishments if e["place_id"] == spec.place_id
        )
        subjects = {s.key: s for s in SUBJECTS}
        selected = [subjects["camila"], subjects["mateo"]]
        state = {
            "source": "backend#219/reference_e2e_dataset",
            "api_url": args.public_api_url or args.api_url,
            "accounts": accounts,
            "establishment": establishment["id"],
            "establishment_name": spec.name,
            "establishment_request": {
                "name": ESTABLISHMENT_REQUESTS[0].name,
                "address": ESTABLISHMENT_REQUESTS[0].formatted_address,
            },
            "subjects": [str(reference_id("subject", s.key)) for s in selected],
            "subject_names": [f"{s.name} {s.last_name}" for s in selected],
            "subject_dnis": [str(s.dni) for s in selected],
            "measurement": {
                # Deliberately outside the usual BMI range to exercise the
                # app's confirmation dialog; this is a fictional UI example.
                "weight": "23",
                "height": str(selected[1].readings[-1].height_cm),
            },
            "seeded_measurements": [
                str(reference_id("measurement", s.key, str(i)))
                for s in SUBJECTS
                for i, _ in enumerate(s.readings)
            ],
        }
        foods = (
            await call("GET", "/food-catalog/foods", search="arroz", page_size=30)
        )["items"]
        state["food"] = next(
            f["id"] for f in foods if f["code"] == "arroz_blanco_crudo"
        )
        state["baseline_movement_ids"] = [
            m["id"]
            for m in (
                await call(
                    "GET",
                    f"/establishments/{state['establishment']}/food-movements",
                    page_size=100,
                )
            )["items"]
        ]
        state["surveys"] = {}
        existing = (await call("GET", "/surveys", page_size=100))["items"]
        for target, title in [
            ("subject", "Seguimiento alimentario"),
            ("establishment", "Relevamiento del comedor"),
            ("anonymous", "Opinión de la comunidad"),
        ]:
            survey = next((s for s in existing if s["name"] == title), None)
            if not survey:
                survey = await call(
                    "POST",
                    "/surveys",
                    {
                        "name": title,
                        "description": (
                            "Encuesta de demostración para el manual de usuario."
                        ),
                        "response_target": target,
                        "requires_response_number": True,
                        "questions": [
                            {
                                "text": "¿Participó de las actividades del comedor?",
                                "response_type": "single_choice",
                                "is_required": True,
                                "options": [{"text": "Sí"}, {"text": "No"}],
                            },
                            {
                                "text": "Observaciones",
                                "response_type": "text",
                                "is_required": False,
                            },
                        ],
                    },
                )
                await call(
                    "PATCH", f"/surveys/{survey['id']}/status", {"is_active": True}
                )
            state["surveys"][target] = survey["id"]
        # The shared seed already covers FIES, pending users, access requests,
        # stock and anthropometry. Only the other survey targets are added here.
        state["surveys"]["fies"] = next(
            s["id"] for s in existing if s["name"] == FIES_SURVEY_NAME
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        print("Shared E2E data ready; manual fixture saved without session tokens.")


if __name__ == "__main__":
    asyncio.run(main())
