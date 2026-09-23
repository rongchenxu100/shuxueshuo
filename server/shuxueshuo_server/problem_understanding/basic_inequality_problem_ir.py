"""Authoring-only conversion from frozen basic-inequality notation to ProblemIR.

This module deliberately stops at the canonical input boundary.  It does not import
planner, method, binding, or proof code.  The resulting payload is suitable for
fixture replay and family matching; ``expected_answers`` and ``route_metadata`` are
kept beside the input and are never put into the solver input.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.family import BASIC_INEQUALITY_FAMILY, FamilyRegistry
from shuxueshuo_server.solver.problem_models import ProblemIR

from .notation_compile import NotationValidator
from .notation_contract import (
    EXPRESSIONS_PATH,
    ROOT as NOTATION_ROOT,
    SCHEMA_PATH,
    SYSTEM_PATH,
    USER_PATH,
)
from .notation_semantics import canonical


REPRESENTATIVE_CASES = (
    "q01", "q03", "q07", "q08", "q12", "q17", "q20", "q25", "q30", "q31",
)
DEFERRED_CASES = "q02,q04-q06,q09-q11,q13-q16,q18-q19,q21-q24,q26-q29"
REQUIRED_SAMPLE_COUNT = 2
_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]*(?![A-Za-z0-9_])")
_DOMAIN_NAMES = {"R", "N", "Z", "Q", "C"}
_RELATION = re.compile(r"(:=|!=|>=|<=|[=≠≥≤><≔≡])")
_EQUALITY_OPERATORS = {"=", ":=", "≔", "≡"}
_RELATION_OPERATORS = _EQUALITY_OPERATORS | {"!=", "≠", ">=", "<=", "≥", "≤", ">", "<"}
_GOAL_TYPES = {
    "find_maximum": "MaximumExpression",
    "find_minimum": "MinimumExpression",
    "find_range": "Range",
    "find_parameter": "ParameterValue",
    "find_value": "ParameterValue",
}


class BasicInequalityProblemIRError(ValueError):
    """Raised when a frozen notation artifact cannot become a safe ProblemIR."""


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return value or "item"


def _scope_id(case_id: str, path: str) -> str:
    return f"scope_{_slug(case_id)}_{_slug(path.replace('/', '_'))}"


def _scope_token(case_id: str, path: str) -> str:
    return _slug(f"{case_id}_{path.replace('/', '_')}")


def _source_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _iter_scopes(scope: Mapping[str, Any], *, path: str = "root", parent: str | None = None):
    label = str(scope.get("label") or path)
    yield scope, path, parent, label
    for index, child in enumerate(scope.get("children", ())):
        if not isinstance(child, Mapping):
            raise BasicInequalityProblemIRError(f"invalid child scope at {path}/children/{index}")
        yield from _iter_scopes(child, path=f"{path}/children/{index}", parent=path)


def _expression_symbols(text: str) -> tuple[str, ...]:
    symbols = []
    for token in _IDENTIFIER.findall(text):
        if token in _DOMAIN_NAMES or token in {"sqrt", "max", "min"}:
            continue
        if token not in symbols:
            symbols.append(token)
    return tuple(symbols)


def _fact_parts(text: str) -> tuple[tuple[str, str], ...]:
    """Return typed source facts without attempting algebraic interpretation."""
    # This converter only lowers individual relations and comparison chains.
    # Boolean structure cannot be flattened safely (especially disjunctions),
    # and commas may separate relations, domains, tuples or function arguments.
    # Reject before the domain shortcut or comparison split can lose structure.
    if re.search(r"[∧∨,，]|\b(?:and|or)\b", text, flags=re.IGNORECASE):
        raise BasicInequalityProblemIRError(
            f"compound logic or comma-separated expressions are not supported: {text}"
        )
    for operator in re.findall(r"[!<>=≠≥≤≔≡:]+", text):
        if operator != ":" and operator not in _RELATION_OPERATORS:
            raise BasicInequalityProblemIRError(f"unsupported relation operator {operator!r}: {text}")
    if "∈" in text:
        return (("symbol_domain", text),)
    pieces = [piece.strip() for piece in _RELATION.split(text)]
    if len(pieces) == 1:
        return (("statement", text),)
    if any(not operand for operand in pieces[::2]):
        raise BasicInequalityProblemIRError(f"relation has an empty operand: {text}")
    # Split adjacent relations and normalize definition operators to equality.
    # The caller keeps the untouched source text on every emitted fact.
    result = []
    for index in range(0, len(pieces) - 2, 2):
        left, operator, right = pieces[index:index + 3]
        fact_type = "equation" if operator in _EQUALITY_OPERATORS else "symbol_constraint"
        operator = "=" if fact_type == "equation" else operator
        result.append((fact_type, f"{left} {operator} {right}"))
    return tuple(result)


def _goal_expression(goal: Mapping[str, Any]) -> str:
    for key in ("expression", "symbol", "object"):
        value = goal.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise BasicInequalityProblemIRError("goal has no expression, symbol, or object")


def _canonical_input(gold: Mapping[str, Any], *, sample_hashes: Sequence[str]) -> dict[str, Any]:
    case_id = str(gold.get("root", {}).get("label") or gold.get("problem_id") or "")
    root = gold.get("root")
    if not case_id or not isinstance(root, Mapping):
        raise BasicInequalityProblemIRError("gold must contain root.label and root")
    if case_id not in REPRESENTATIVE_CASES:
        raise BasicInequalityProblemIRError(
            f"{case_id}: stage 1 only accepts representative cases "
            + ",".join(REPRESENTATIVE_CASES)
        )
    if gold.get("match_status") != "matched" or gold.get("family_id") != "basic_inequality":
        raise BasicInequalityProblemIRError(f"{case_id}: frozen family match is not basic_inequality")
    if any(scope.get("uncertainties") for scope, *_ in _iter_scopes(root)):
        raise BasicInequalityProblemIRError(f"{case_id}: unresolved notation uncertainty")

    scopes: list[dict[str, Any]] = []
    scope_ids: dict[str, str] = {}
    for scope, path, parent, label in _iter_scopes(root):
        sid = _scope_id(case_id, path)
        scope_ids[path] = sid
        scopes.append({
            "scope_id": sid,
            "label": label,
            "parent": scope_ids.get(parent) if parent else None,
            "source_path": f"/root{path.removeprefix('root')}",
        })

    entities: list[dict[str, Any]] = []
    visible_entities: dict[str, dict[str, str]] = {}
    for scope, path, parent, _label in _iter_scopes(root):
        # Inherit ancestors only. A symbol first used in a child stays local;
        # a sibling's symbol with the same spelling is a separate entity.
        visible = dict(visible_entities[parent]) if parent else {}
        sources: dict[str, tuple[str, str]] = {}
        for field in ("definitions", "facts", "goals"):
            for index, item in enumerate(scope.get(field, ())):
                text = _goal_expression(item) if field == "goals" and isinstance(item, Mapping) else item
                if isinstance(text, str):
                    for symbol in _expression_symbols(text):
                        sources.setdefault(symbol, (f"/root{path.removeprefix('root')}/{field}/{index}", text))
        for symbol in sorted(sources):
            if symbol in visible:
                continue
            handle = f"symbol:{_scope_token(case_id, path)}:{_slug(symbol)}"
            source_path, source_text = sources[symbol]
            entities.append({
                "handle": handle,
                "entity_type": "symbol",
                "name": symbol,
                "scope_id": scope_ids[path],
                "description": f"代数符号 {symbol}",
                "source_path": source_path,
                "source_text": source_text,
                "normalized_expression": symbol,
                "sample_hashes": list(sample_hashes),
            })
            visible[symbol] = handle
        visible_entities[path] = visible
    if not entities:
        raise BasicInequalityProblemIRError(f"{case_id}: no symbol entity")

    facts: list[dict[str, Any]] = []
    goals: list[dict[str, Any]] = []
    for scope, path, _parent, _label in _iter_scopes(root):
        sid = scope_ids[path]
        entity_by_name = visible_entities[path]
        for source_field, prefix in (("definitions", "d"), ("facts", "f")):
            for fact_index, original in enumerate(scope.get(source_field, ())):
                if not isinstance(original, str) or not original.strip():
                    continue
                for part_index, (fact_type, expression) in enumerate(_fact_parts(original)):
                    handle = f"fact:{_scope_token(case_id, path)}:{prefix}{fact_index}_{part_index}"
                    referenced = [entity_by_name[name] for name in _expression_symbols(original) if name in entity_by_name]
                    facts.append({
                        "handle": handle,
                        "type": fact_type,
                        "scope_id": sid,
                        "valid_scope": sid,
                        "description": expression,
                        "source_path": f"/root{path.removeprefix('root')}/{source_field}/{fact_index}",
                        "source_text": original,
                        "normalized_expression": expression,
                        "entity_handles": referenced,
                        "sample_hashes": list(sample_hashes),
                    })
        for goal_index, goal in enumerate(scope.get("goals", ())):
            if not isinstance(goal, Mapping):
                raise BasicInequalityProblemIRError(f"{case_id}: invalid goal at {path}/goals/{goal_index}")
            kind = str(goal.get("kind") or "")
            value_type = _GOAL_TYPES.get(kind)
            if value_type is None:
                raise BasicInequalityProblemIRError(f"{case_id}: unsupported goal kind {kind!r}")
            expression = _goal_expression(goal)
            goals.append({
                "handle": f"answer:{_scope_token(case_id, path)}_g{goal_index}",
                "scope_id": sid,
                "valid_scope": sid,
                "answer_key": f"{case_id}_g{goal_index}",
                "value_type": value_type,
                "required": True,
                "description": f"{kind}: {expression}",
                "goal_kind": kind,
                "target_expression": expression,
                "source_path": f"/root{path.removeprefix('root')}/goals/{goal_index}",
                "source_text": expression,
                "normalized_expression": expression,
                "sample_hashes": list(sample_hashes),
            })

    if not any(item["type"] in {"equation", "symbol_constraint"} for item in facts):
        raise BasicInequalityProblemIRError(f"{case_id}: no equation or symbol_constraint fact")
    if not any(item["value_type"] in {"MaximumExpression", "MinimumExpression", "Range", "ParameterValue"} for item in goals):
        raise BasicInequalityProblemIRError(f"{case_id}: no supported extremum/range/parameter goal")

    original_text = str(gold.get("original_text") or "").strip()
    return {
        "problem_id": case_id,
        "pattern": "basic-inequality",
        "problem_type": "basic_inequality",
        "display": {"page_title": case_id, "summary": original_text},
        "original_text": {
            "source": "basic-inequality frozen notation gold",
            "number": case_id,
            "lines": [original_text],
        },
        "scopes": scopes,
        "entities": entities,
        "facts": facts,
        "question_goals": goals,
    }


def validate_family_match(
    canonical_input: Mapping[str, Any],
    *,
    candidate_family_id: str = "basic_inequality",
) -> dict[str, Any]:
    """Match through an authoring-only registry and enforce source primitives."""
    if candidate_family_id != "basic_inequality":
        raise BasicInequalityProblemIRError("candidate family label is not basic_inequality")
    if canonical_input.get("pattern") != "basic-inequality" or canonical_input.get("problem_type") != "basic_inequality":
        raise BasicInequalityProblemIRError("basic inequality requires its canonical pattern and problem_type")
    entities = canonical_input.get("entities", ())
    facts = canonical_input.get("facts", ())
    goals = canonical_input.get("question_goals", ())
    if not any(item.get("entity_type") == "symbol" for item in entities if isinstance(item, Mapping)):
        raise BasicInequalityProblemIRError("family source requirement missing symbol entity")
    if not any(item.get("type") in {"equation", "symbol_constraint"} for item in facts if isinstance(item, Mapping)):
        raise BasicInequalityProblemIRError("family source requirement missing equation or symbol_constraint")
    if not any(item.get("value_type") in {"MaximumExpression", "MinimumExpression", "Range", "ParameterValue"} for item in goals if isinstance(item, Mapping)):
        raise BasicInequalityProblemIRError("family source requirement missing extremum/range/parameter goal")
    problem = ProblemIR(
        problem_id=str(canonical_input["problem_id"]),
        pattern=str(canonical_input["pattern"]),
        problem_type=str(canonical_input["problem_type"]),
        symbols=[str(item["name"]) for item in entities if isinstance(item, Mapping) and item.get("entity_type") == "symbol"],
    )
    matched = FamilyRegistry((BASIC_INEQUALITY_FAMILY,)).match(problem)
    if matched is None or matched.family_id != "basic_inequality":
        raise BasicInequalityProblemIRError("authoring-only family registry did not match basic_inequality")
    return {"family_id": matched.family_id, "matched_by": ["pattern", "problem_type"]}


def _sample_contract_hashes(
    samples: Sequence[Mapping[str, Any]],
    sample_ids: Sequence[str],
    sample_hashes: Sequence[str],
) -> dict[str, Any]:
    """Use the extraction contract recorded by every sample, never today's files."""
    if len(samples) != REQUIRED_SAMPLE_COUNT:
        raise BasicInequalityProblemIRError("sample_provenance must contain exactly 2 sample records")
    contracts = []
    for sample, sample_id, sample_hash in zip(samples, sample_ids, sample_hashes, strict=True):
        if not isinstance(sample, Mapping) or sample.get("sample_id") != sample_id or sample.get("sha256") != sample_hash:
            raise BasicInequalityProblemIRError("sample_provenance must match sample_ids and sample_hashes in order")
        templates = sample.get("template_files")
        if not isinstance(templates, Mapping):
            raise BasicInequalityProblemIRError("sample_provenance is missing template_files")
        hashes = {
            key: templates.get(str(path.relative_to(NOTATION_ROOT)))
            for key, path in (("system", SYSTEM_PATH), ("user", USER_PATH), ("schema", SCHEMA_PATH), ("expressions", EXPRESSIONS_PATH))
        }
        hashes["families"] = sample.get("notation_family_catalog_hash")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value) for value in hashes.values()):
            raise BasicInequalityProblemIRError("sample_provenance requires recorded SHA-256 hashes for every prompt, schema and catalog")
        contracts.append({
            "prompt_hashes": {key: hashes[key] for key in ("system", "user")},
            "schema_hash": hashes["schema"],
            "catalog_hashes": {key: hashes[key] for key in ("expressions", "families")},
        })
    if contracts[0] != contracts[1]:
        raise BasicInequalityProblemIRError("sample_provenance contract hashes must agree across all samples")
    return contracts[0]


def build_problem_ir_artifact(
    gold: Mapping[str, Any],
    *,
    gold_path: str | Path = "",
    image_path: str | Path = "",
    sample_hashes: Sequence[str] = (),
    sample_ids: Sequence[str] = ("sample-01", "sample-02"),
    sample_provenance: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build an audited artifact from two explicitly supplied sample hashes.

    Hashes identify actual sample outputs, never the gold. Independent calls may
    return identical output, so sample IDs must be distinct but hashes need not be.
    Each sample's recorded extraction contract is required and must agree; current
    workspace prompt files cannot stand in for historical sample provenance.
    """
    report = NotationValidator().validate(dict(gold))
    if not report.ok:
        raise BasicInequalityProblemIRError(f"notation gold is invalid: {report.payload()}")
    if not canonical(report):
        raise BasicInequalityProblemIRError("notation gold has no canonical semantic payload")
    gold_bytes = json.dumps(gold, ensure_ascii=False, sort_keys=True).encode("utf-8")
    gold_sha = sha256(gold_bytes).hexdigest()
    if not (len(sample_hashes) == len(sample_ids) == REQUIRED_SAMPLE_COUNT):
        raise BasicInequalityProblemIRError(
            "sample_hashes and sample_ids must both contain exactly "
            f"{REQUIRED_SAMPLE_COUNT} samples; explicit live sample hashes are required"
        )
    if any(not isinstance(item, str) or not item.strip() for item in sample_ids) or len(set(sample_ids)) != REQUIRED_SAMPLE_COUNT:
        raise BasicInequalityProblemIRError("sample_ids must be non-empty and distinct")
    if any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", item) for item in sample_hashes):
        raise BasicInequalityProblemIRError("sample_hashes must contain SHA-256 hex digests")
    hashes = tuple(sample_hashes)
    contract_hashes = _sample_contract_hashes(sample_provenance, sample_ids, hashes)
    canonical_input = _canonical_input(gold, sample_hashes=hashes)
    family_match = validate_family_match(canonical_input)
    canonical_bytes = json.dumps(canonical_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema_version": "basic-inequality-problem-ir/v1",
        "problem_id": canonical_input["problem_id"],
        "meta": {
            "problem_id": canonical_input["problem_id"],
            "title": (
                canonical_input["original_text"]["lines"][0]
                or canonical_input["problem_id"]
            ),
        },
        "input": canonical_input,
        "family_match": family_match,
        "provenance": {
            "gold_path": str(gold_path),
            "gold_sha256": gold_sha,
            "sample_ids": list(sample_ids),
            "sample_hashes": list(hashes),
            "required_sample_count": REQUIRED_SAMPLE_COUNT,
            "image_path": str(image_path),
            "notation_contract": "problem-math-notation/v1",
            **contract_hashes,
            "canonical_hash": sha256(canonical_bytes).hexdigest(),
            "deferred_cases": DEFERRED_CASES,
        },
    }


def build_problem_ir_from_file(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    path = Path(path)
    return build_problem_ir_artifact(json.loads(path.read_text(encoding="utf-8")), gold_path=path, **kwargs)


__all__ = [
    "BasicInequalityProblemIRError",
    "DEFERRED_CASES",
    "REPRESENTATIVE_CASES",
    "build_problem_ir_artifact",
    "build_problem_ir_from_file",
    "validate_family_match",
]
