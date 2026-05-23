import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _slugify_service_name(value: str) -> str:
    """Convert the service name into a filename-safe slug."""
    slug = value.strip().lower().replace("_", "-").replace(" ", "-")
    return "".join(ch for ch in slug if ch.isalnum() or ch == "-")


def main() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from app.core.config import settings
    from app.main import app

    schema = app.openapi()
    service_name = sys.argv[1] if len(sys.argv) > 1 else settings.service_name

    service_slug = _slugify_service_name(service_name)
    filename = f"{service_slug}.openapi.generated.json"

    output_path = PROJECT_ROOT / "docs" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    print(f"OK: {output_path}")


if __name__ == "__main__":
    main()
