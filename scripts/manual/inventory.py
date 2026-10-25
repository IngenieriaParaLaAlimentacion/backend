# Generated Markdown prose and table rows are kept on single source lines.
# ruff: noqa: E501
"""Index every web page and Android feature screen against the manual chapters."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".context/manual"
DOC = ROOT / "docs/manual-usuario"


def module(path):
    text = str(path).lower()
    if any(s in text for s in ["/food/", "/stock", "recipe", "foodmovement"]):
        return "04-nutrir.md"
    if "survey" in text:
        return "03-encuestas.md"
    if any(s in text for s in ["measurement", "/subject/", "/subjects/"]):
        return "02-talla-y-peso.md"
    return "01-acceso.md"


def main():
    entries, versions = [], {}
    for repo in ["backend", "backoffice", "app_mobile"]:
        checkout = WORK / repo
        versions[repo] = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        if repo == "backend":
            continue
        sources = (
            sorted((checkout / "app").rglob("page.tsx"))
            if repo == "backoffice"
            else sorted(
                (checkout / "composeApp/src/commonMain/kotlin").rglob("*Screen.kt")
            )
        )
        for source in sources:
            rel = str(source.relative_to(checkout))
            entries.append(
                {
                    "repository": repo,
                    "source": rel,
                    "chapter": module(rel),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "url": f"https://github.com/IngenieriaParaLaAlimentacion/{repo}/blob/{versions[repo]}/{rel}",
                }
            )
    manifests = []
    for filename in ["web-captures.json", "android-captures.json"]:
        path = WORK / "screenshots" / filename
        if path.exists():
            manifests.extend(json.loads(path.read_text()))
    captures = [
        {k: e[k] for k in ["id", "surface", "file", "expected", "capturedAt"]}
        for e in manifests
        if (WORK / "screenshots" / e["file"]).is_file()
    ]
    report = {"revisions": versions, "screens": entries, "captures": captures}
    (DOC / "inventario.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    lines = [
        "# Cobertura y evidencias de esta edición",
        "",
        "El inventario registra las páginas web y los archivos de pantallas nativas encontrados en las revisiones fijadas. Una pantalla inventariada o capturada no implica que todas sus alternativas hayan sido ejecutadas.",
        "",
        "## Revisiones",
        "",
        "| Repositorio | Revisión |",
        "|---|---|",
    ]
    lines += [f"| {repo} | `{sha}` |" for repo, sha in versions.items()]
    lines += [
        "",
        "## Comprobaciones de recorridos",
        "",
        "| Recorrido | Evidencia y alcance |",
        "|---|---|",
        "| Acceso web y consulta de secciones | Playwright inicia sesión por la interfaz real; cada captura espera un texto propio de su pantalla. |",
        "| Medición sin conexión → sincronización | App Android: selección del sujeto, carga, confirmación, aviso de pendiente offline y estado sincronizado en Historial. |",
        "| Consulta y evolución de mediciones | Backoffice real con datos persistidos y apertura del gráfico por Playwright. |",
        "| Exportación de mediciones | Descarga CSV real mediante Playwright; archivo conservado en `.context/manual/downloads/`. |",
        "| Recibos y recetas | Respuesta del modelo y almacenamiento de objetos sustituidos explícitamente por servicios locales de demostración. No valida Gemini ni R2. |",
        "| Recibo: propuesta automática | Incompatibilidad comprobada: el backend no envía needs_review y el DTO Android lo exige. La alternativa manual con foto sí se guardó. |",
        "| Invitaciones, recuperación y verificación de email | Procedimientos revisados en código; entrega de correo y recorrido completo del enlace pendientes de comprobación con un buzón de prueba. |",
        "| Casos de permisos, validación y errores | Documentados a partir de UI, contratos y código. La lista de capturas no acredita ejecución exhaustiva de todas las combinaciones. |",
        "| iOS | Sin capturas ni ejecución de esta edición. |",
        "",
        f"## Inventario de pantallas ({len(entries)})",
        "",
        "Cada fuente está enlazada a la revisión exacta y asociada a un capítulo. Los componentes y diálogos se revisan junto con su pantalla; el inventario no cuenta cada componente como una función independiente.",
        "",
        "| Interfaz | Pantalla o ruta | Capítulo |",
        "|---|---|---|",
    ]
    for entry in entries:
        label = (
            entry["source"]
            .replace(
                "composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/",
                "",
            )
            .replace("app/dashboard/", "dashboard/")
        )
        lines.append(
            f"| {entry['repository']} | [{label}]({entry['url']}) | [{entry['chapter']}]({entry['chapter']}) |"
        )
    live = WORK / "scenarios.json"
    if live.exists():
        checks = json.loads(live.read_text())
        (DOC / "verificaciones.json").write_text(live.read_text())
        lines += [
            "",
            "## Verificaciones sobre datos persistidos",
            "",
            f"Ejecutadas: {checks['verifiedAt']}. Entorno local aislado; modelo de demostración.",
            "",
            "| Recorrido | Resultado | Evidencia |",
            "|---|---|---|",
        ]
        lines += [
            f"| {e['scenario']} | {e['result']} | {e['evidence']} |"
            for e in checks["scenarios"]
        ]
    lines += [
        "",
        f"## Capturas con comprobación de pantalla ({len(captures)})",
        "",
        "| Captura | Interfaz | Texto comprobado antes de capturar |",
        "|---|---|---|",
    ]
    for entry in sorted(captures, key=lambda e: e["id"]):
        lines.append(
            f"| [{entry['id']}](assets/{entry['file']}) | {entry['surface']} | {entry['expected']} |"
        )
    lines += [
        "",
        "Los datos de demostración, las capturas originales y las descargas se generan localmente. El inventario público no conserva URLs con parámetros de autenticación ni tokens.",
        "",
    ]
    (DOC / "cobertura.md").write_text("\n".join(lines))
    print(f"Indexed {len(entries)} screens, {len(captures)} captures")


if __name__ == "__main__":
    main()
