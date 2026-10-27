from typing import Any


def structured_schema(source: dict[str, Any]) -> dict[str, Any]:
    """Return a closed-object strict JSON schema for the provider request."""

    def visit(value):
        if isinstance(value, list):
            return [visit(child) for child in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, child in value.items():
            if key in {"nullable", "default", "title"}:
                continue
            if key in {
                "properties",
                "$defs",
                "definitions",
                "patternProperties",
                "dependentSchemas",
            }:
                result[key] = {name: visit(schema) for name, schema in child.items()}
            elif key in {
                "items",
                "prefixItems",
                "additionalItems",
                "contains",
                "additionalProperties",
                "unevaluatedProperties",
                "unevaluatedItems",
                "propertyNames",
                "allOf",
                "anyOf",
                "oneOf",
                "not",
                "if",
                "then",
                "else",
            }:
                result[key] = visit(child)
            else:
                result[key] = child
        if result.get("type") == "object" or "properties" in result:
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        if value.get("nullable") is True:
            result = {"anyOf": [result, {"type": "null"}]}
        return result

    return visit(source)
