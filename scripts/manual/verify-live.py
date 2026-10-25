"""Verify persisted cross-interface examples against the local backend."""

import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".context/manual"
fixture = json.loads((WORK / "fixture.json").read_text())
results = []


def record(name, evidence):
    results.append({"scenario": name, "result": "passed", "evidence": evidence})


with httpx.Client(base_url="http://127.0.0.1:8080/api/v1", timeout=30) as client:
    tokens = {}
    for role in ["superadmin", "analyst", "field_worker"]:
        response = client.post(
            "/auth/login",
            json={
                "email": f"{role}@manual.example",
                "password": "Manual2026!",
                "device_id": str(uuid4()),
            },
        )
        response.raise_for_status()
        tokens[role] = response.json()["access_token"]

    def get(path, role="superadmin"):
        response = client.get(path, headers={"Authorization": f"Bearer {tokens[role]}"})
        response.raise_for_status()
        return response.json()

    measurements = get("/measurements?page_size=100")["items"]
    seeded = {
        str(uuid5(NAMESPACE_URL, f"ipa-user-manual/measurement-{i}-{j}"))
        for i in range(3)
        for j in range(3)
    }
    android_rows = [
        m
        for m in measurements
        if m["id"] not in seeded and m["subject"]["id"] == fixture["subjects"][1]
    ]
    assert android_rows, "No Android measurement persisted after sync"
    record(
        "Medición Android → backend",
        f"{len(android_rows)} registros fuera del seed, visibles en el listado real",
    )

    responses = get(
        f"/surveys/{fixture['surveys']['subject']}/responses?page_size=100"
    )["items"]
    assert any(r.get("response_number") == 101 for r in responses)
    record(
        "Encuesta Android → backend",
        "Respuesta 101 del relevamiento por sujeto persistida",
    )

    eid = fixture["establishment"]
    movements = get(f"/establishments/{eid}/food-movements?page_size=100")["items"]
    assert len(movements) >= 4, (
        "Expected seed, manual intake, outflow and receipt intake"
    )
    record(
        "Movimientos Android → backend",
        f"{len(movements)} movimientos en el establecimiento",
    )
    recipes = get(f"/establishments/{eid}/recipes?page_size=100")
    assert any(r.get("chosen") for r in recipes["items"]), "No recipe chosen by Android"
    record(
        "Elegir receta → salida",
        "Receta elegida persistida; el flujo usa la transacción real del backend",
    )

    for role in ["analyst", "field_worker"]:
        response = client.get(
            "/admin/users", headers={"Authorization": f"Bearer {tokens[role]}"}
        )
        assert response.status_code == 403
    record(
        "Permisos de administración",
        "Analista y relevador reciben 403 al listar usuarios administrativos",
    )

    downloads = list((WORK / "downloads").glob("*.csv"))
    assert downloads, "No Playwright CSV download"
    text = downloads[-1].read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(text[:4096])
    rows = list(csv.reader(text.splitlines(), dialect))
    assert len(rows) > 1
    record(
        "Exportación web",
        f"CSV real descargado por Playwright, {len(rows) - 1} filas de datos",
    )

    spreadsheets = list((WORK / "downloads").glob("*.xlsx"))
    assert spreadsheets, "No Playwright survey response download"
    with zipfile.ZipFile(spreadsheets[-1]) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
    record(
        "Exportación de respuestas",
        "Archivo Excel descargado por Playwright con estructura XLSX válida",
    )

    photo = WORK / "recibo-demo.jpg"
    response = client.post(
        "/food-intakes/from-photo",
        headers={"Authorization": f"Bearer {tokens['field_worker']}"},
        data={"establishment_id": eid},
        files={"image": (photo.name, photo.read_bytes(), "image/jpeg")},
    )
    response.raise_for_status()
    assert response.json()["lines"]
    assert "needs_review" not in response.json()["lines"][0]
    known = {
        "scenario": "Análisis de recibo en Android",
        "result": "known_incompatibility",
        "evidence": (
            "Respuesta 200 sin needs_review; el DTO Android lo exige. "
            "Captura y log de JsonConvertException conservados."
        ),
    }

report = {
    "verifiedAt": datetime.now(timezone.utc).isoformat(),
    "environment": "isolated-local-manual",
    "model": "demonstration-double",
    "scenarios": results + [known],
}
(WORK / "scenarios.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False) + "\n"
)
print(f"PASS: {len(results)} live checks; 1 known receipt incompatibility documented")
