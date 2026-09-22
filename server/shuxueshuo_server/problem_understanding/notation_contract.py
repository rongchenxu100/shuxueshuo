"""Versioned wire schema and prompts loaded from reviewable external files."""

import json
from pathlib import Path

CONTRACT = "problem-math-notation/v1"
ROOT = Path(__file__).resolve().parents[3]
SYSTEM_PATH = ROOT / "internal/llm-prompts/problem-math-notation-system.md"
USER_PATH = ROOT / "internal/llm-prompts/problem-math-notation-user.md"
SCHEMA_PATH = ROOT / "internal/schemas/problem-math-notation-v1.schema.json"
EXPRESSIONS_PATH = ROOT / "internal/llm-prompts/problem-math-notation-expressions.json"
FAMILY_CATALOG_PATH = ROOT / "internal/llm-prompts/problem-math-notation-families.json"
TEMPLATE_FILES = (SYSTEM_PATH, USER_PATH, SCHEMA_PATH, EXPRESSIONS_PATH)


def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def expression_catalog():
    return json.loads(EXPRESSIONS_PATH.read_text(encoding="utf-8"))


SYSTEM = SYSTEM_PATH.read_text(encoding="utf-8").strip()
USER_SUFFIX = USER_PATH.read_text(encoding="utf-8").strip()
NOTATION = schema()["$defs"]["Scope"]["properties"]["facts"]["items"]["description"]


def prompt_payload(*, registry, observation, **metadata):
    from .observation import observation_view

    return {
        "registered_families": registry,
        "ocr_hints": observation_view(observation)[0],
        "auxiliary_text_origin": observation.get(
            "evidence_origin", "recorded_ocr_observation"
        ),
        "response_schema": schema(),
        "math_expression_catalog": expression_catalog(),
    }
