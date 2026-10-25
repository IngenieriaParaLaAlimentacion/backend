"""Prepare fictional records in a dedicated local manual database.

Run with the backend virtualenv, from its checkout, with that checkout on
PYTHONPATH. Never use this script against a shared or production database.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from sqlalchemy import select

from app.config.settings import settings
from app.core.security import hash_password
from app.db.database import AsyncSessionLocal
from app.models.auth.user import User
from app.models.auth.user_password import UserPassword


def stable(value):
    return str(uuid5(NAMESPACE_URL, "ipa-user-manual/" + value))


async def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = str(settings.database_url)
    if "127.0.0.1:55432/manual" not in url:
        raise SystemExit("Requires the dedicated localhost:55432/manual database")
    password = "Manual2026!"
    async with AsyncSessionLocal() as session:
        for role, name, last in [
            ("superadmin", "Lucía", "Administradora"),
            ("admin", "Mariana", "Coordinadora"),
            ("analyst", "Diego", "Analista"),
            ("field_worker", "Ana", "Relevadora"),
        ]:
            email = f"{role}@manual.example"
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                from uuid import UUID

                user = User(
                    id=UUID(stable(role)),
                    name=name,
                    last_name=last,
                    email=email,
                    role=role,
                    status="active",
                    is_email_verified=True,
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                session.add(
                    UserPassword(
                        user_id=user.id, password_hashed=hash_password(password)
                    )
                )
        await session.commit()

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8080/api/v1", timeout=60
    ) as client:
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
            if response.is_error:
                raise RuntimeError(
                    f"{method} {path}: {response.status_code} {response.text}"
                )
            return response.json() if response.content else None

        for role in ["superadmin", "admin", "analyst", "field_worker"]:
            result = await call(
                "POST",
                "/auth/login",
                {
                    "email": f"{role}@manual.example",
                    "password": password,
                    "device_id": str(uuid4()),
                },
                role=role,
            )
            tokens[role] = result["access_token"]
        state = {"users": {r: stable(r) for r in tokens}}
        items = (await call("GET", "/establishments", page_size=100))["items"]
        name = "Comedor Semillas del Sur"
        establishment = next((e for e in items if e["name"] == name), None)
        if establishment is None:
            establishment = await call(
                "POST",
                "/establishments",
                {
                    "name": name,
                    "formatted_address": "Av. San Martín 1200, San Miguel de Tucumán",
                    "latitude": -26.8241,
                    "longitude": -65.2226,
                    "place_id": "manual-semillas-del-sur",
                    "city": "San Miguel de Tucumán",
                    "province": "Tucumán",
                },
            )
        eid = state["establishment"] = establishment["id"]
        for role in ["field_worker", "analyst"]:
            links = await call("GET", "/users/me/establishments", role=role)
            if not any(
                str(x.get("id", x.get("establishment_id"))) == eid for x in links
            ):
                await call(
                    "POST",
                    "/users/me/establishments",
                    {"establishment_ids": [eid]},
                    role=role,
                )
            await call(
                "PATCH",
                f"/admin/field-worker/{stable(role)}/establishments/approve",
                {"establishment_ids": [eid]},
            )
        state["subjects"] = []
        now = datetime.now(timezone.utc)
        for i, (first, last, dni, sex, birth, weight, height) in enumerate(
            [
                ("Sofía", "Ejemplo", 91000001, "female", "2018-03-12", 26, 126),
                ("Mateo", "Demostración", 91000002, "male", "2017-07-05", 23, 135),
                ("Valentina", "Prueba", 91000003, "female", "2016-11-20", 44, 132),
            ]
        ):
            sid = stable(f"subject-{i}")
            await call(
                "POST",
                "/subjects",
                {
                    "id": sid,
                    "dni": dni,
                    "sex": sex,
                    "name": first,
                    "last_name": last,
                    "birth_date": birth,
                    "is_rural": False,
                    "is_indigenous": False,
                },
            )
            state["subjects"].append(sid)
            for j in range(3):
                await call(
                    "POST",
                    "/measurements",
                    {
                        "id": stable(f"measurement-{i}-{j}"),
                        "subject_id": sid,
                        "establishment_id": eid,
                        "weight_kg": weight - j * 0.5,
                        "height_cm": height - j,
                        "measured_at": (now - timedelta(days=j * 30 + 1)).isoformat(),
                        "observation": (
                            "Control de seguimiento. Datos ficticios del manual."
                        ),
                    },
                    role="field_worker",
                )
        foods = (
            await call("GET", "/food-catalog/foods", search="arroz", page_size=30)
        )["items"]
        state["food"] = foods[0]["id"]
        await call(
            "POST",
            "/food-intakes",
            {
                "id": stable("intake"),
                "establishment_id": eid,
                "occurred_at": (now - timedelta(days=1)).isoformat(),
                "origin_type": "private_donation",
                "is_recurring": True,
                "comments": "Donación semanal de demostración",
                "items": [{"food_id": state["food"], "quantity": 25}],
            },
            role="field_worker",
        )
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
        fies_title = "Seguridad alimentaria FIES"
        fies = next((s for s in existing if s["name"] == fies_title), None)
        if not fies:
            template = await call("GET", "/surveys/templates/fies")
            fies = await call(
                "POST",
                "/surveys",
                {
                    "name": fies_title,
                    "description": template["description"],
                    "response_target": "subject",
                    "instrument_type": "fies",
                    "requires_response_number": False,
                    "questions": [
                        {k: q[k] for k in ["text", "response_type", "is_required"]}
                        | {"options": [{"text": o["text"]} for o in q["options"]]}
                        for q in template["questions"]
                    ],
                },
            )
            await call("PATCH", f"/surveys/{fies['id']}/status", {"is_active": True})
        state["surveys"]["fies"] = fies["id"]
        detail = await call("GET", f"/surveys/{fies['id']}")
        await call(
            "POST",
            f"/surveys/{fies['id']}/responses",
            {
                "id": stable("fies-response"),
                "subject_id": state["subjects"][1],
                "event_at": now.isoformat(),
                "answers": {
                    q["id"]: q["options"][i % 2]["id"]
                    for i, q in enumerate(detail["questions"])
                },
            },
            role="field_worker",
        )
        pending = await client.post(
            "/auth/register/field-worker",
            json={
                "email": "registro@manual.example",
                "password": password,
                "name": "Elena",
                "last_name": "Registro de prueba",
                "establishments": [eid],
                "locality": "San Miguel de Tucumán",
            },
        )
        if pending.status_code not in (201, 409):
            raise RuntimeError(f"Pending registration: {pending.status_code}")
        requests = (await call("GET", "/admin/establishment-requests", page_size=100))[
            "items"
        ]
        if not any(
            r["name"] == "Comedor Esperanza" and r["status"] == "pending"
            for r in requests
        ):
            await call(
                "POST",
                "/establishments/requests",
                {"name": "Comedor Esperanza", "formatted_address": "Belgrano 2500"},
                role="field_worker",
            )
        args.output.write_text(json.dumps(state, indent=2))
        print("Manual fixture prepared; identifiers saved (no authentication tokens).")


if __name__ == "__main__":
    asyncio.run(main())
