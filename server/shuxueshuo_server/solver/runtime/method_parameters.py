"""Candidate parameters are validated data, never state or executable code."""

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator


def validate_parameters(schema: dict | None, parameters: Any) -> dict:
    schema = schema or {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    Draft202012Validator(schema).validate(parameters)
    return deepcopy(parameters)
