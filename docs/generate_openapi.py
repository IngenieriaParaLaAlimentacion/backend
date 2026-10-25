import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _slugify_service_name(value: str) -> str:
    """Convert the service name into a filename-safe slug."""
    slug = value.strip().lower().replace("_", "-").replace(" ", "-")
    return "".join(ch for ch in slug if ch.isalnum() or ch == "-")


def filter_tag(schema: dict, tag: str) -> dict:
    """Keep operations for one tag and their transitive component references."""
    paths = {
        path: {
            method: operation
            for method, operation in operations.items()
            if isinstance(operation, dict) and tag in operation.get("tags", [])
        }
        for path, operations in schema["paths"].items()
    }
    paths = {path: operations for path, operations in paths.items() if operations}
    components = {
        "securitySchemes": schema.get("components", {}).get("securitySchemes", {})
    }

    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/"):
                _, _, kind, name = reference.split("/")
                bucket = components.setdefault(kind, {})
                if name not in bucket:
                    bucket[name] = schema["components"][kind][name]
                    collect(bucket[name])
            for child in value.values():
                collect(child)

    collect(paths)
    return {**schema, "paths": paths, "components": components}


def main() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from app.config.settings import settings
    from app.main import app

    parser = argparse.ArgumentParser()
    parser.add_argument("service_name", nargs="?", default=settings.service_name)
    parser.add_argument("--tag", help="Export only operations carrying this tag")
    args = parser.parse_args()
    schema = app.openapi()
    if args.tag:
        schema = filter_tag(schema, args.tag)
    service_name = args.service_name

    service_slug = _slugify_service_name(service_name)
    filename = f"{service_slug}.openapi.generated.json"

    output_path = PROJECT_ROOT / "docs" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    print(f"OK: {output_path}")


if __name__ == "__main__":
    main()
