from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def _build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.setdefault("components", {})
    components_schemas = components.setdefault("schemas", {})
    components_schemas.setdefault(
        "ProblemDetail",
        {
            "type": "object",
            "description": (
                "RFC 7807 problem details. `type` is the stable machine-readable "
                "identifier clients should branch on; `title` and `detail` are "
                "human-readable prose and may change without notice."
            ),
            "properties": {
                "type": {"type": "string", "examples": ["/errors/survey-locked"]},
                "title": {"type": "string"},
                "status": {"type": "integer"},
                "detail": {"type": "string"},
                "instance": {"type": "string"},
            },
            "required": ["type", "title", "status", "detail", "instance"],
            # Extension members (e.g. canonical_subject, existing_response) are
            # open-ended by RFC 7807 and are documented in docs/errors.md.
            "additionalProperties": True,
        },
    )

    problem_json_content = {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
        }
    }

    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue

            responses = operation.setdefault("responses", {})

            # The exposed contract reports malformed client input as 400 even
            # though FastAPI raises 422 -- see "422 vs 400" in docs/api.md.
            if responses.pop("422", None) is not None:
                responses.setdefault("400", {"description": "Invalid request payload"})

            # No route declares a 500 today, so the canonical unhandled-error
            # envelope would otherwise be undiscoverable from the schema.
            responses.setdefault("500", {"description": "Unexpected internal error"})

            for status_code, response in list(responses.items()):
                if not isinstance(response, dict):
                    continue

                if status_code == "default" or status_code.startswith(("4", "5")):
                    response["content"] = dict(problem_json_content)

    for leftover in ("HTTPValidationError", "ValidationError"):
        components_schemas.pop(leftover, None)

    app.openapi_schema = schema
    return app.openapi_schema


def configure_openapi(app: FastAPI) -> None:
    """Register a custom OpenAPI schema builder on the FastAPI app."""

    def custom_openapi() -> dict[str, Any]:
        return _build_openapi_schema(app)

    app.openapi = custom_openapi
