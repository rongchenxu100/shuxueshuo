"""Authoring-only lowering of bound scalar notation; no solving or dispatch."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.family import BASIC_INEQUALITY_FAMILY, FamilyRegistry
from shuxueshuo_server.solver.problem_models import ProblemIR

from .identity import revision
from .notation_compile import NotationValidator, Report, normalize
from .notation_contract import schema
from .notation_parser import NotationError

REPRESENTATIVE_CASES = (
    "q01",
    "q03",
    "q07",
    "q08",
    "q12",
    "q17",
    "q20",
    "q25",
    "q30",
    "q31",
)
DEFERRED_CASES = "q02,q04-q06,q09-q11,q13-q16,q18-q19,q21-q24,q26-q29"
GOAL_TYPES = {
    "find_maximum": "MaximumExpression",
    "find_minimum": "MinimumExpression",
    "find_range": "Range",
}
SUPPORTED_GOALS = {*GOAL_TYPES.values(), "ParameterValue"}


class BasicInequalityProblemIRError(ValueError):
    """Unsupported, ambiguous or unauditable authoring input."""


def _walk(ast):
    yield ast
    for child in ast[1:]:
        if isinstance(child, list):
            yield from _walk(child)


def _text(ast, names):
    """Print existing bound syntax without algebraic rewriting."""
    kind = ast[0]
    if kind == "ref" and ast[2] == "scalar":
        return names[ast[1]]
    if kind == "number":
        return ast[1]
    if kind == "neg":
        return f"(-{_text(ast[1], names)})"
    if kind in {"+", "-", "*", "/", "^", "=", "!=", "<", "<=", ">", ">="}:
        return f"({_text(ast[1], names)}{kind}{_text(ast[2], names)})"
    if kind == "call" and ast[1] == "sqrt":
        return f"sqrt({_text(ast[2], names)})"
    if kind == "real":
        return "ℝ"
    if kind == "default_domain":
        return f"{_text(ast[1], names)} ∈ ℝ"
    if kind == "interval":
        return (
            ("[" if ast[1] else "(")
            + _text(ast[3], names)
            + ","
            + _text(ast[4], names)
            + ("]" if ast[2] else ")")
        )
    if kind == "∈":
        return f"{_text(ast[1], names)} ∈ {_text(ast[2], names)}"
    raise BasicInequalityProblemIRError(f"unsupported scalar notation: {kind}")


def _relations(ast):
    if ast[0] == "and":
        for child in ast[1:]:
            yield from _relations(child)
    elif ast[0] in {"=", "!=", "<", "<=", ">", ">=", "default_domain", "∈"}:
        yield ast
    else:
        # Disjunctions, quantifiers and prose are not silently flattened.
        raise BasicInequalityProblemIRError(f"unsupported fact structure: {ast[0]}")


def _constant_exponent(ast):
    """Read literal rational exponents without evaluating symbolic expressions."""
    if ast[0] == "number":
        return Fraction(ast[1])
    if ast[0] == "neg":
        return -_constant_exponent(ast[1])
    if ast[0] == "/":
        numerator, denominator = map(_constant_exponent, ast[1:])
        if denominator == 0:
            raise BasicInequalityProblemIRError("zero denominator in rational exponent")
        return numerator / denominator
    raise BasicInequalityProblemIRError(
        "unsupported exponent for domain obligations: expected a literal rational constant"
    )


def convert_notation(gold, *, problem_id, sample_refs=()):
    """Pure syntax/binding projection. IDs never select mathematical behavior.

    Schema validation and the existing lexical binder are reused without running
    semantic normalization or equivalence proofs. This is also the unit-test
    entrypoint; an audited artifact is only built by the frozen-file entrypoint.
    """
    errors = list(Draft202012Validator(schema()).iter_errors(gold))
    if errors:
        raise BasicInequalityProblemIRError(
            f"invalid notation schema: {errors[0].message}"
        )
    if (
        gold["match_status"] != "matched"
        or gold["family_id"] != BASIC_INEQUALITY_FAMILY.family_id
    ):
        raise BasicInequalityProblemIRError("candidate family label mismatch")
    source = normalize(gold)
    report = Report()
    try:
        bound = NotationValidator().scope(source["root"], report, "r")
    except (NotationError, ValueError, TypeError, RecursionError) as exc:
        raise BasicInequalityProblemIRError("notation binding failed") from exc
    if not report.ok:
        raise BasicInequalityProblemIRError(f"notation binding failed: {report.issues}")
    if any(obj["kind"] != "scalar" for obj in report.objects):
        raise BasicInequalityProblemIRError("only scalar source objects are supported")
    names = {obj["ref"]: obj["name"] for obj in report.objects}
    handles = {}
    scopes, facts, goals = [], [], []
    occurrences = {ref: [] for ref in names}
    scope_map = {}

    def evidence(path, text, ast):
        data = {
            "source_path": path,
            "source_text": text,
            "normalized_expression": _text(ast, names),
            "sample_refs": list(sample_refs),
        }
        for ref in dict.fromkeys(n[1] for n in _walk(ast) if n[0] == "ref"):
            occurrences[ref].append(deepcopy(data))
        return data

    def obligations(ast):
        """Unverified local real-domain conditions, not a domain solver.

        Powers require literal rational exponents; unsupported exponent forms
        fail closed instead of emitting an incomplete list of conditions.
        """
        result = []

        def visit_expression(node):
            target = None
            op = "!="
            if node[0] == "/":
                target = node[2]
            elif node[:2] == ["call", "sqrt"]:
                target, op = node[2], ">="
            elif node[0] == "^":
                exponent = _constant_exponent(node[2])
                if exponent.denominator % 2 == 0:
                    target, op = node[1], ">" if exponent < 0 else ">="
                elif exponent < 0:
                    target = node[1]
            if target is not None:
                result.append(
                    {
                        "expression": f"{_text(target, names)} {op} 0",
                        "status": "unverified",
                        "origin": "expression_domain",
                    }
                )
            # A rational exponent's '/' is part of the exponent literal, not
            # an independent division in the expression's variable domain.
            children = [node[1]] if node[0] == "^" else node[1:]
            for child in children:
                if isinstance(child, list):
                    visit_expression(child)

        visit_expression(ast)
        return result

    def visit(raw, compiled, path, parent=None):
        if raw["uncertainties"]:
            raise BasicInequalityProblemIRError(f"unresolved uncertainty at {path}")
        sid = f"s{len(scopes)}"
        scope_map[compiled["scope"]] = sid
        scopes.append(
            {
                "scope_id": sid,
                "label": raw["label"],
                "parent": parent,
                "source_path": path,
            }
        )
        # Register local entities once their actual scope ID is assigned.
        # Ancestor handles remain available to child facts; sibling symbols
        # with the same name receive different scope segments.
        for obj in report.objects:
            if obj["scope"] == compiled["scope"]:
                handles[obj["ref"]] = f"symbol:{sid}:{obj['name']}"
        expressions = [
            (f"{path}/{field}/{index}", text)
            for field in ("definitions", "facts")
            for index, text in enumerate(raw[field])
        ]
        if len(expressions) != len(compiled["facts"]):
            raise BasicInequalityProblemIRError(
                "source/bound fact cardinality mismatch"
            )
        for (location, original), ast in zip(
            expressions, compiled["facts"], strict=True
        ):
            for relation in _relations(ast):
                kind = relation[0]
                fact_type = (
                    "equation"
                    if kind == "="
                    else "symbol_domain"
                    if kind in {"default_domain", "∈"}
                    else "symbol_constraint"
                )
                if kind == "∈" and relation[2][0] not in {"interval", "real"}:
                    raise BasicInequalityProblemIRError("unsupported source domain")
                facts.append(
                    {
                        "handle": f"fact:{sid}:f{len(facts)}",
                        "type": fact_type,
                        "scope_id": sid,
                        "valid_scope": sid,
                        "description": original,
                        "expression": _text(relation, names),
                        "relation_operator": kind,
                        "bound_expression": deepcopy(relation),
                        "entity_handles": list(
                            dict.fromkeys(
                                handles[n[1]] for n in _walk(relation) if n[0] == "ref"
                            )
                        ),
                        "domain_obligations": obligations(relation),
                        **evidence(location, original, relation),
                    }
                )
        for index, (goal, target) in enumerate(
            zip(raw["goals"], compiled["goals"], strict=True)
        ):
            kind, ast = goal["kind"], target["target"]
            typ = GOAL_TYPES.get(kind)
            if kind == "find_value":
                # A source request for the value of a single parameter is
                # different from evaluating a general scalar expression.
                typ = "ParameterValue" if ast[0] == "ref" else "ScalarExpression"
            if typ is None:
                raise BasicInequalityProblemIRError(f"unsupported goal: {kind}")
            field = next(k for k in ("expression", "symbol", "object") if k in goal)
            original = goal[field]
            goals.append(
                {
                    "handle": f"answer:{sid}.g{index}",
                    "scope_id": sid,
                    "valid_scope": sid,
                    "answer_key": f"{sid}_g{index}",
                    "value_type": typ,
                    "required": True,
                    "description": f"{kind}: {original}",
                    "goal_kind": kind,
                    "target_expression": original,
                    "bound_expression": deepcopy(ast),
                    "variables": deepcopy(target.get("variables", [])),
                    "in_terms_of": deepcopy(target.get("in_terms_of", [])),
                    "domain_obligations": obligations(ast),
                    **evidence(f"{path}/goals/{index}/{field}", original, ast),
                }
            )
        for index, (child, compiled_child) in enumerate(
            zip(raw["children"], compiled["children"], strict=True)
        ):
            visit(child, compiled_child, f"{path}/children/{index}", sid)

    visit(source["root"], bound, "/root")
    entities = []
    for obj in report.objects:
        locations = occurrences[obj["ref"]]
        if not locations:
            raise BasicInequalityProblemIRError("symbol has no source occurrence")
        entities.append(
            {
                "handle": handles[obj["ref"]],
                "entity_type": "symbol",
                "name": obj["name"],
                "scope_id": scope_map[obj["scope"]],
                "description": f"代数符号 {obj['name']}",
                "notation_ref": obj["ref"],
                **locations[0],
                "source_occurrences": locations,
            }
        )
    original = gold.get("original_text", "").strip()
    if not original:
        raise BasicInequalityProblemIRError("source original_text is required")
    return {
        "problem_id": problem_id,
        "pattern": "basic-inequality",
        "problem_type": "basic_inequality",
        "display": {"page_title": problem_id, "summary": original},
        "original_text": {
            "source": "frozen notation",
            "number": problem_id,
            "lines": [original],
        },
        "scopes": scopes,
        "entities": entities,
        "facts": facts,
        "question_goals": goals,
    }


def validate_family_match(canonical_input, *, candidate_family_id, registry=None):
    registry = registry or FamilyRegistry((BASIC_INEQUALITY_FAMILY,))
    problem = ProblemIR(
        problem_id=canonical_input["problem_id"],
        pattern=canonical_input["pattern"],
        problem_type=canonical_input["problem_type"],
        symbols=[
            e["name"]
            for e in canonical_input["entities"]
            if e["entity_type"] == "symbol"
        ],
    )
    matched = registry.match(problem)
    if matched is None or matched.family_id != "basic_inequality":
        raise BasicInequalityProblemIRError("no basic_inequality structural match")
    if candidate_family_id != matched.family_id:
        raise BasicInequalityProblemIRError("candidate family label mismatch")
    if not problem.symbols:
        raise BasicInequalityProblemIRError("missing symbol entity")
    if not any(
        f["type"] in {"equation", "symbol_constraint"} for f in canonical_input["facts"]
    ):
        raise BasicInequalityProblemIRError("missing equation or symbol_constraint")
    goals = canonical_input["question_goals"]
    if not goals:
        raise BasicInequalityProblemIRError("missing supported goal")
    if not all(g["value_type"] in SUPPORTED_GOALS for g in goals):
        raise BasicInequalityProblemIRError("unsupported goal: all goals must be supported")
    return {
        "family_id": matched.family_id,
        "matched_by": ["pattern", "problem_type"],
        "source_requirements_verified": True,
        "authoring_only": True,
    }


def build_problem_ir_from_file(path):
    """Validate frozen extraction evidence before lowering to an audited artifact."""
    from .basic_inequality_frozen import load_verified_case

    path = Path(path)
    verified = load_verified_case(path)
    refs = [
        {key: sample[key] for key in ("sample_id", "response_id", "raw_sha256")}
        for sample in verified["provenance"]["samples"]
    ]
    payload = convert_notation(verified["gold"], problem_id=path.stem, sample_refs=refs)
    match = validate_family_match(
        payload, candidate_family_id=verified["gold"]["family_id"]
    )
    return {
        "schema_version": "basic-inequality-problem-ir/v1",
        "meta": {"problem_id": path.stem, "title": payload["display"]["summary"]},
        "input": payload,
        "family_match": match,
        "provenance": {
            **verified["provenance"],
            "input_semantic_sha256": revision(payload),
        },
    }
