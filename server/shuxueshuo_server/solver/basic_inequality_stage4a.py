"""Explicit authoring Runtime entry for scalar maximum problems (Stage 4A).

Only code-owned source projection lives here. Plans, answers and mathematical
routes are never derived from problem IDs or expected fixtures.
"""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import sympy as sp

from shuxueshuo_server.problem_understanding.runtime_binding import (
    NotationRuntimeBundle,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemEntity,
    ProblemFact,
    ProblemGoal,
    ProblemGraph,
    ProblemScope,
    ProblemSource,
    ProblemUnitRecord,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    RuntimeProjectionManifest,
    SolverProblemProjection,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityToken,
    audit_runtime_projection,
)
from shuxueshuo_server.solver.extraction.source_identity import freeze_json, stable_hash
from shuxueshuo_server.solver.family.basic_inequality_runtime import (
    STAGE4A_FAMILY_REGISTRY,
)
from shuxueshuo_server.solver.math_kernel.expression_parser import (
    parse_math_expression,
    parse_math_relation,
)
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input


def build_authoring_bundle(source_input):
    """Adapt canonical source data; caller explicitly opts into authoring runtime."""
    original = deepcopy(source_input)
    family = STAGE4A_FAMILY_REGISTRY.match(problem_from_canonical_input(original))
    if family is None:
        raise ValueError("unsupported basic inequality source")
    if len(original["scopes"]) != 1 or len(original["question_goals"]) != 1:
        raise ValueError("Stage 4A supports one scalar maximum goal in one scope")
    goal = original["question_goals"][0]
    if (goal["value_type"], goal["goal_kind"]) not in {
        ("MaximumExpression", "find_maximum"),
        ("MinimumExpression", "find_minimum"),
    }:
        raise ValueError("Stage 4A requires an explicit maximum-expression goal")
    answer_key = "maximum" if goal["goal_kind"] == "find_maximum" else "minimum"
    if any(e["entity_type"] != "symbol" for e in original["entities"]):
        raise ValueError("Stage 4A only accepts declared scalar symbols")
    if any(
        f["type"] not in {"equation", "symbol_constraint"} for f in original["facts"]
    ):
        raise ValueError("unsupported source condition")
    scope = original["scopes"][0]["scope_id"]
    if any(
        item["scope_id"] != scope
        for key in ("entities", "facts", "question_goals")
        for item in original[key]
    ):
        raise ValueError("source scope mismatch")
    if original["scopes"][0]["parent"] is not None:
        raise ValueError("Stage 4A requires a root scope")
    for key, identity in (
        ("entities", "name"),
        ("entities", "handle"),
        ("facts", "handle"),
    ):
        if len({item[identity] for item in original[key]}) != len(original[key]):
            raise ValueError("duplicate source identity")
    # Root scope remapping is mechanical; source paths stay in the frozen input.
    entities = [
        {**e, "handle": f"symbol:problem:{e['name']}", "scope_id": "problem"}
        for e in original["entities"]
    ]
    facts = [
        {
            "handle": f"fact:problem:condition_{i}",
            "type": f["type"],
            "scope_id": "problem",
            "valid_scope": "problem",
            "math": f["normalized_expression"],
            "description": f["source_text"],
            "source_path": f["source_path"],
        }
        for i, f in enumerate(original["facts"])
    ]
    symbols = {e["name"]: sp.Symbol(e["name"], real=True) for e in entities}
    for fact in facts:
        relation = parse_math_relation(fact["math"], symbols)
        if fact["type"] == "equation" and relation.ast.op != "=":
            raise ValueError("equation source must contain an equality")
        if fact["type"] == "symbol_constraint":
            left, right = relation.ast.children
            if left.op != "symbol":
                raise ValueError("Stage 4A requires scalar-variable domain conditions")
            value = parse_math_expression(
                fact["math"][right.span[0] : right.span[1]], symbols
            ).to_sympy(symbols)
            if value.free_symbols:
                raise ValueError("Stage 4A requires constant domain endpoints")
            fact.update(
                subject=f"symbol:problem:{left.text}",
                operator=relation.ast.op,
                value=str(value),
            )
    target = {
        "handle": f"fact:problem:{answer_key}_target",
        "type": "extremum_target",
        "scope_id": "problem",
        "valid_scope": "problem",
        "description": goal["description"],
        "goal_kind": goal["goal_kind"],
        "target_math": goal["target_expression"],
        **(
            {"expression_owner": "function:problem:target_expression"}
            if answer_key == "minimum"
            else {}
        ),
        "scalar_symbols": [e["name"] for e in entities],
        "source_conditions": [
            {key: f[key] for key in ("handle", "math", "source_path")} for f in facts
        ],
        "source_path": goal["source_path"],
        "source_input_hash": stable_hash(original),
    }
    if answer_key == "minimum":
        entities.append(
            {
                "handle": "function:problem:target_expression",
                "name": "target_expression",
                "entity_type": "function",
                "function_type": "scalar_expression",
                "scope_id": "problem",
                "expression": goal["target_expression"],
                "description": "原题目标表达式（可整理的状态）",
            }
        )
    canonical = {
        **original,
        "scopes": [{"scope_id": "problem", "label": "题目", "parent": None}],
        "entities": entities,
        "facts": [*facts, target],
        "question_goals": [
            {
                **goal,
                "handle": f"answer:problem.{answer_key}",
                "scope_id": "problem",
                "valid_scope": "problem",
                "answer_key": answer_key,
            }
        ],
    }
    source_hash = stable_hash(original)

    def uid(kind, value):
        return kind + ":" + stable_hash([source_hash, value])

    graph_entities = tuple(
        ProblemEntity(uid("entity", e["name"]), e["name"], e["entity_type"], e["name"])
        for e in entities
    )
    graph_facts = tuple(
        ProblemFact(
            uid("fact", f["handle"]),
            f["type"],
            (
                {
                    "symbol": f["subject"].rsplit(":", 1)[-1],
                    "operator": f["operator"],
                    "value": f["value"],
                    "math": f["math"],
                }
                if f["type"] == "symbol_constraint"
                else {"math": f["math"]}
            )
            if f != target
            else {
                "target_math": target["target_math"],
                "goal_kind": goal["goal_kind"],
                "conditions": [f["math"] for f in facts],
            },
        )
        for f in canonical["facts"]
    )
    graph_goal = ProblemGoal(
        uid("goal", goal["handle"]),
        f"{answer_key}_value",
        answer_key,
        {"expression": {"math": target["target_math"]}},
    )
    root = ProblemScope(
        uid("scope", scope),
        "problem",
        "题目",
        tuple(original["original_text"]["lines"]),
        graph_entities,
        graph_facts,
        (graph_goal,),
        (),
        ("problem",),
    )
    graph = ProblemGraph(
        original["problem_id"], family.family_id, ProblemSource(""), root
    )
    pairs = [("scope:problem", root, "scope")]
    pairs += [
        (e["handle"], g, "entity")
        for e, g in zip(entities, graph_entities, strict=True)
    ]
    pairs += [
        (f["handle"], g, "fact")
        for f, g in zip(canonical["facts"], graph_facts, strict=True)
    ]
    pairs += [(f"answer:problem.{answer_key}", graph_goal, "goal")]
    units = {
        item.unit_id: ProblemUnitRecord(
            item.unit_id,
            kind,
            "problem",
            stable_hash(item.wire_payload()),
            getattr(item, "local_id", None),
        )
        for _, item, kind in pairs
    }
    sources = {handle: (item.unit_id,) for handle, item, _ in pairs}
    manifest = RuntimeProjectionManifest(
        original["problem_id"],
        family.family_id,
        source_hash,
        graph.semantic_hash,
        sources,
        {},
    )
    index = audit_runtime_projection(
        SolverProblemProjection(
            canonical, problem_from_canonical_input(canonical), manifest
        ),
        {key: unit.to_payload() for key, unit in units.items()},
    )
    token = ProblemBundleAuthorityToken(
        "stage4a:" + source_hash,
        source_hash,
        source_hash,
        graph.semantic_hash,
        stable_hash(canonical),
    )
    return NotationRuntimeBundle(
        token,
        graph,
        MappingProxyType(units),
        freeze_json(canonical),
        manifest,
        index,
        freeze_json(original),
        freeze_json({}),
        admission_evidence=freeze_json(
            {"kind": "explicit_authoring", "source_hash": source_hash}
        ),
    )


def load_frozen_authoring_bundle(gold_path, problem_ir_path):
    """Replay two real frozen samples and compare the deterministic IR before admission."""
    from shuxueshuo_server.problem_understanding.basic_inequality_problem_ir import (
        build_problem_ir_from_file,
    )

    artifact = build_problem_ir_from_file(gold_path)
    stored = json.loads(Path(problem_ir_path).read_text(encoding="utf-8"))
    if artifact != stored:
        raise ValueError("frozen ProblemIR differs from verified extraction replay")
    bundle = build_authoring_bundle(artifact["input"])
    provenance = artifact["provenance"]
    return replace(
        bundle,
        provenance=freeze_json(provenance),
        source_artifact_ids=(provenance["gold_sha256"],),
        admission_evidence=freeze_json(
            {
                "kind": "verified_frozen_authoring",
                "source_hash": stable_hash(artifact["input"]),
                "provenance_hash": stable_hash(provenance),
            }
        ),
    )
