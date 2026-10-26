from typing import Any


def structured_schema(source: dict[str, Any]) -> dict[str, Any]:
    """Return a closed-object strict JSON schema for the provider request."""

    def visit(value):
        if isinstance(value, list):
            return [visit(child) for child in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: visit(child)
            for key, child in value.items()
            if key not in {"nullable", "default", "title"}
        }
        if result.get("type") == "object" or "properties" in result:
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        if value.get("nullable") is True:
            result = {"anyOf": [result, {"type": "null"}]}
        return result

    return visit(source)
