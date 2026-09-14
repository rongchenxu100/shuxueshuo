"""Compact JSON Schema serialization for prompts, without changing validation.

This module only removes annotations and factors identical schema nodes. Any
intentional prompt/runtime policy difference belongs in the contract generator.
"""

from collections import Counter
from copy import deepcopy
import json
from typing import Any


def compact_prompt_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep wire constraints while sharing repeated nodes through local $refs."""
    maps = {"$defs", "properties", "patternProperties", "dependentSchemas"}
    singles = {
        "additionalProperties", "unevaluatedProperties", "propertyNames",
        "items", "contains", "not", "if", "then", "else", "unevaluatedItems",
    }
    arrays = {"allOf", "anyOf", "oneOf", "prefixItems"}

    def children(node, transform):
        result = deepcopy(node)
        for key, value in node.items():
            if key in maps:
                result[key] = {name: transform(item) for name, item in value.items()}
            elif key in singles:
                result[key] = transform(value)
            elif key in arrays:
                result[key] = [transform(item) for item in value]
        return result

    def shorten(node):
        if not isinstance(node, dict):
            return node
        result = children(node, shorten)
        result.pop("description", None)
        result.pop("title", None)
        # Draft 2020-12 applies siblings of $ref; the single allOf is redundant.
        conjunction = result.get("allOf")
        if isinstance(conjunction, list) and len(conjunction) == 1:
            only = conjunction[0]
            if isinstance(only, dict) and set(only) == {"$ref"} and "$ref" not in result:
                result.pop("allOf")
                result.update(only)
        # (base AND A) OR (base AND B) == base AND (A OR B).
        alternatives = result.get("oneOf")
        if alternatives and "allOf" not in result and all(
            isinstance(item, dict) and set(item) == {"allOf"}
            and len(item["allOf"]) == 2 for item in alternatives
        ):
            base = alternatives[0]["allOf"][0]
            if all(item["allOf"][0] == base for item in alternatives):
                result.pop("oneOf")
                result["allOf"] = [base, {"oneOf": [item["allOf"][1] for item in alternatives]}]
        return result

    result = shorten(schema)
    # Keep the protocol label once; all verbose field annotations live in Catalog.
    if "title" in schema:
        result["title"] = schema["title"]
    counts: Counter[str] = Counter()

    def signature(node):
        return json.dumps(node, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def count(node):
        if isinstance(node, dict):
            counts[signature(node)] += 1
            children(node, count)
        return node

    count(result)
    definitions = result.setdefault("$defs", {})
    shared: dict[str, str] = {}
    added: dict[str, Any] = {}

    def factor(node):
        if not isinstance(node, dict):
            return node
        key = signature(node)
        # Require a net saving after including a definition and its references.
        n = counts[key]
        worthwhile = n > 1 and (n - 1) * len(key) > n * 38 + 40
        if worthwhile and key in shared:
            return {"$ref": f"#/$defs/{shared[key]}"}
        value = children(node, factor)
        if worthwhile:
            name = f"shared_{len(shared)}"
            while name in definitions or name in added:
                name += "_"
            shared[key] = name
            added[name] = value
            return {"$ref": f"#/$defs/{name}"}
        return value

    result = factor(result)
    result["$defs"].update(added)
    return result
