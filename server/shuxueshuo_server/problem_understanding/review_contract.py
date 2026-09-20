"""External review/repair instructions; all wire versions belong to requests."""

import json
import re
from dataclasses import replace

from jsonschema import Draft202012Validator

from .candidate_common import strict_json
from .identity import revision
from .notation_contract import (
    CONTRACT as CANDIDATE_CONTRACT,
)
from .notation_contract import ROOT, TEMPLATE_FILES, expression_catalog, schema

CONTRACT = "problem-math-source-review/v1"
REPAIR_PATH = ROOT / "internal/llm-prompts/problem-math-notation-repair.md"
REVIEW_PATH = ROOT / "internal/llm-prompts/problem-math-notation-review.md"
EXAMPLES_PATH = (
    ROOT / "internal/llm-prompts/problem-math-notation-review-few-shots.json"
)
FAMILIES_PATH = ROOT / "internal/llm-prompts/problem-math-notation-review-families.json"
SCHEMA_PATH = ROOT / "internal/schemas/problem-math-source-review-v1.schema.json"
FILES = (
    *TEMPLATE_FILES,
    REPAIR_PATH,
    REVIEW_PATH,
    EXAMPLES_PATH,
    FAMILIES_PATH,
    SCHEMA_PATH,
)


class ReviewFamilyCatalogError(ValueError):
    """A review catalog must cover registered IDs without legacy fallback."""


def review_family_context(registry):
    """Use registered IDs only; never pass Solver authoring instructions to review."""
    try:
        catalog = strict_json(FAMILIES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewFamilyCatalogError("review.invalid_family_catalog") from exc

    def text_list(value):
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value)
        )

    if (
        not isinstance(catalog, dict)
        or set(catalog) != {"review_scope", "families"}
        or not text_list(catalog["review_scope"])
        or not isinstance(catalog["families"], list)
    ):
        raise ReviewFamilyCatalogError("review.invalid_family_catalog")
    indexed = {}
    fields = {"family_id", "title", "source_conditions", "source_conflicts"}
    for entry in catalog["families"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != fields
            or any(
                not isinstance(entry[key], str) or not entry[key].strip()
                for key in ("family_id", "title")
            )
            or not text_list(entry["source_conditions"])
            or not text_list(entry["source_conflicts"])
            or entry["family_id"] in indexed
        ):
            raise ReviewFamilyCatalogError("review.invalid_family_catalog")
        indexed[entry["family_id"]] = entry
    selected, seen = [], set()
    for family in registry:
        family_id = family.get("family_id") if isinstance(family, dict) else None
        if not isinstance(family_id, str) or not family_id or family_id in seen:
            raise ReviewFamilyCatalogError("review.invalid_family_registry")
        if family_id not in indexed:
            raise ReviewFamilyCatalogError(f"review.family_catalog_missing:{family_id}")
        seen.add(family_id)
        selected.append(indexed[family_id])
    return {
        "family_review_scope": catalog["review_scope"],
        "registered_families": selected,
    }


def pointer(value, path):
    if path == "":
        return value
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("review.invalid_pointer")
    if re.search(r"~(?![01])", path):
        raise ValueError("review.invalid_pointer_escape")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdecimal() or str(int(part)) != part:
                raise ValueError("review.invalid_index")
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise ValueError("review.invalid_pointer")  # noqa: TRY004 - invalid path, not caller type
    return value


def review_schema():
    return json.loads(SCHEMA_PATH.read_text())


def finding_target(candidate, kind, path):
    """Validate an exact review location; never widen a bad pointer to an ancestor."""
    if kind == "wrong_transcription":
        expected = "/original_text" if "original_text" in candidate else ""
        if path != expected:
            raise ValueError("review.invalid_transcription_pointer")
    elif path == "":
        raise ValueError("review.invalid_global_pointer")
    return pointer(candidate, path)


def validate_review(raw, candidate):
    value = strict_json(raw)
    Draft202012Validator(review_schema()).validate(value)
    for finding in value["findings"]:
        finding_target(candidate, finding["kind"], finding["path"])
    return value


def candidate_contract_summary():
    """Derive field meanings from the actual contract, without its repeated rules."""
    contract = schema()
    scope = contract["$defs"]["Scope"]
    variants = scope["properties"]["goals"]["items"]["oneOf"]
    shared_fields = ("in_terms_of", "variables")
    return {
        "original_text": contract["properties"]["original_text"]["description"],
        "scope": scope["description"],
        "goal_kinds": [
            {
                "kind": goal["properties"]["kind"]["const"],
                "meaning": goal["description"],
                "required": goal["required"],
                "optional": [
                    key for key in goal["properties"] if key not in goal["required"]
                ],
            }
            for goal in variants
        ],
        "goal_fields": {
            field: next(
                goal["properties"][field]["description"]
                for goal in variants
                if field in goal["properties"]
            )
            for field in shared_fields
        },
        "match": contract["properties"]["match_status"]["description"],
    }


def code_validation_summary(base, candidate, registry, validation):
    """Only attest to checks of this exact candidate, source and registry."""
    if not validation or (
        validation.get("contract") != CANDIDATE_CONTRACT
        or validation.get("revision") != revision(candidate)
        or validation.get("binding", {}).get("source_sha256")
        != base.evidence_pack.source_revision_hash
        or validation.get("binding", {}).get("registry_snapshot") != revision(registry)
        or validation.get("contract_valid") is not True
        or validation.get("reports", {}).get("ir", {}).get("ok") is not True
        or validation.get("reports", {}).get("match", {}).get("ok") is not True
    ):
        raise ValueError("review.invalid_validation_context")
    return {
        "candidate_revision": validation["revision"],
        "json_schema": "passed",
        "notation_and_bindings": "passed",
        "match_declaration": "passed",
        "source_alignment": "not_checked",
        "family_semantics": "not_checked",
        "mathematical_equivalence": "partial",
    }


def request_for(
    base,
    stage,
    candidate,
    registry,
    diagnostics=(),
    feedback=(),
    *,
    validation=None,
):
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        MultimodalExtractionPrompt,
    )

    review = stage == "review"
    output_schema = review_schema() if review else schema()
    payload = {
        "response_schema": output_schema,
        "math_expression_catalog": expression_catalog(),
    }
    if review:
        payload.update(
            **review_family_context(registry),
            candidate=candidate,
            candidate_contract=candidate_contract_summary(),
            code_validation=code_validation_summary(
                base, candidate, registry, validation
            ),
            few_shots=json.loads(EXAMPLES_PATH.read_text()),
        )
    else:
        payload.update(
            registered_families=registry,
            base_candidate=candidate,
            diagnostics=list(diagnostics),
            repair_feedback=list(feedback),
        )
    return replace(
        base,
        contract_version=CONTRACT if review else base.contract_version,
        contract_schema=output_schema,
        prompt=MultimodalExtractionPrompt(
            (REVIEW_PATH if review else REPAIR_PATH).read_text().strip(),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "对照完整原图，只返回本次响应 Schema 规定的 JSON。",
        ),
    )
