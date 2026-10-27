"""Versioned, family-free extraction contracts for graph lesson stage one."""

import json
from pathlib import Path

CONTRACT = "graph-problem-extraction/v2"
REVIEW_CONTRACT = "graph-problem-review/v2"
RESULT_CONTRACT = "graph-stage-one-result/v2"
ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = ROOT / "internal/schemas/graph-problem-extraction-v2.schema.json"
REVIEW_SCHEMA_PATH = ROOT / "internal/schemas/graph-problem-review-v2.schema.json"
RESULT_SCHEMA_PATH = ROOT / "internal/schemas/graph-stage-one-result-v2.schema.json"
SYSTEM_PATH = ROOT / "internal/llm-prompts/graph-stage-one-system.md"
REVIEW_PATH = ROOT / "internal/llm-prompts/graph-stage-one-review.md"
REPAIR_PATH = ROOT / "internal/llm-prompts/graph-stage-one-repair.md"
SOURCE_RULES_PATH = ROOT / "internal/llm-prompts/graph-stage-one-source-rules.md"
BASE_EXPRESSIONS_PATH = (
    ROOT / "internal/llm-prompts/problem-math-notation-expressions.json"
)
EXPRESSIONS_PATH = ROOT / "internal/llm-prompts/graph-stage-one-expressions.json"
TEMPLATE_FILES = (
    SCHEMA_PATH,
    REVIEW_SCHEMA_PATH,
    RESULT_SCHEMA_PATH,
    SYSTEM_PATH,
    REVIEW_PATH,
    REPAIR_PATH,
    SOURCE_RULES_PATH,
    BASE_EXPRESSIONS_PATH,
    EXPRESSIONS_PATH,
)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def schema():
    return _read(SCHEMA_PATH)


def review_schema():
    return _read(REVIEW_SCHEMA_PATH)


def result_schema():
    return _read(RESULT_SCHEMA_PATH)


def expression_catalog():
    """Apply explicit stage-one policy overrides without changing old consumers."""
    catalog = _read(BASE_EXPRESSIONS_PATH)
    overlay = _read(EXPRESSIONS_PATH)
    catalog["version"] = overlay["version"]
    catalog["expressions"] = [
        overlay["overrides"].get(entry["id"], entry) for entry in catalog["expressions"]
    ] + overlay.get("additions", [])
    return catalog


SOURCE_RULES = SOURCE_RULES_PATH.read_text(encoding="utf-8").strip()


def _prompt(path):
    return path.read_text(encoding="utf-8").strip() + "\n\n" + SOURCE_RULES


SYSTEM = _prompt(SYSTEM_PATH)
REVIEW_SYSTEM = _prompt(REVIEW_PATH)
REPAIR_SYSTEM = _prompt(REPAIR_PATH)
