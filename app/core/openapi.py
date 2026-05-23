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
            "properties": {
                "type": {
                    "type": "string",
                    "default": "about:blank",
                    "example": "about:blank",
                },
                "title": {"type": "string"},
                "status": {"type": "integer"},
                "detail": {"type": "string"},
                "instance": {"type": "string"},
            },
            "required": ["type", "title", "status", "detail", "instance"],
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
            had_422 = responses.pop("422", None) is not None

            if had_422:
                bad_request_response = responses.setdefault(
                    "400", {"description": "Invalid request payload"}
                )
                if isinstance(bad_request_response, dict):
                    bad_request_response.setdefault(
                        "description", "Invalid request payload"
                    )
                    content = bad_request_response.setdefault("content", {})
                    content.setdefault(
                        "application/problem+json",
                        problem_json_content["application/problem+json"],
                    )

            for status_code, response in list(responses.items()):
                if not isinstance(response, dict):
                    continue

                if status_code == "default" or status_code.startswith(("4", "5")):
                    content = response.setdefault("content", {})
                    content.setdefault(
                        "application/problem+json",
                        problem_json_content["application/problem+json"],
                    )

    for leftover in ("HTTPValidationError", "ValidationError"):
        components_schemas.pop(leftover, None)

    app.openapi_schema = schema
    return app.openapi_schema


def configure_openapi(app: FastAPI) -> None:
    """Register a custom OpenAPI schema builder on the FastAPI app."""

    def custom_openapi() -> dict[str, Any]:
        return _build_openapi_schema(app)

    app.openapi = custom_openapi
