from typing import Any

# Keywords whose value maps a name to a schema: the names are not keywords.
_NAMED_SCHEMAS = {
    "properties",
    "$defs",
    "definitions",
    "patternProperties",
    "dependentSchemas",
}

# Keywords whose value is a schema, or a list of them.
_SUBSCHEMAS = {
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
}

_BOUNDS = {
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "format",
    "title",
    "default",
}


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
            if key in _NAMED_SCHEMAS:
                result[key] = {name: visit(schema) for name, schema in child.items()}
            elif key in _SUBSCHEMAS:
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


def without_bounds(source: dict[str, Any]) -> dict[str, Any]:
    """Return ``source`` without lengths, sizes, formats, titles and defaults.

    Field and definition names are kept, whatever they are called, and so are
    literal values such as the members of an ``enum``.
    """

    # Bounds on long texts and nested arrays can exceed the complexity a provider
    # accepts in strict structured output. The caller validates them on the answer.
    def visit(value):
        if isinstance(value, list):
            return [visit(child) for child in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, child in value.items():
            if key in _BOUNDS:
                continue
            if key in _NAMED_SCHEMAS:
                result[key] = {name: visit(schema) for name, schema in child.items()}
            elif key in _SUBSCHEMAS:
                result[key] = visit(child)
            else:
                result[key] = child
        return result

    return visit(source)
