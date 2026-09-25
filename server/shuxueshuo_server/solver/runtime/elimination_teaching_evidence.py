"""Public M08 teaching evidence without proof certificates."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

import sympy as sp

CONTRACT = "elimination-teaching-evidence/v1"


@dataclass(frozen=True)
class EliminationTeachingEvidence:
    step_id: str
    data_json: str

    def __post_init__(self):
        if (
            not self.step_id
            or self.data.get("kind") != "verified_constraint_elimination"
        ):
            raise ValueError("invalid elimination teaching evidence")
        if not all(
            self.data.get(k) for k in ("source", "result", "relations", "restoration")
        ):
            raise ValueError("incomplete elimination teaching evidence")

    @property
    def data(self):
        return json.loads(self.data_json)

    @property
    def schema_version(self):
        return CONTRACT

    @property
    def evidence_id(self):
        return (
            "elimination:"
            + hashlib.sha256(
                json.dumps(self.to_payload(False), sort_keys=True).encode()
            ).hexdigest()
        )

    def to_payload(self, include_id=True):
        data = {"schema_version": CONTRACT, "step_id": self.step_id, "data": self.data}
        if include_id:
            data["evidence_id"] = self.evidence_id
        return data

    def authority_payload(self):
        return self.to_payload()

    @classmethod
    def from_payload(cls, raw):
        if (
            set(raw) != {"schema_version", "step_id", "data", "evidence_id"}
            or raw["schema_version"] != CONTRACT
        ):
            raise ValueError("invalid elimination evidence payload")
        item = cls(raw["step_id"], json.dumps(raw["data"], sort_keys=True))
        if raw["evidence_id"] != item.evidence_id:
            raise ValueError("elimination evidence hash mismatch")
        return item


def elimination_teaching_evidence_schema():
    return {
        "title": "EliminationTeachingEvidence",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "step_id", "data", "evidence_id"],
        "properties": {
            "schema_version": {"const": CONTRACT},
            "step_id": {"type": "string", "minLength": 1},
            "data": {"type": "object"},
            "evidence_id": {"type": "string", "minLength": 1},
        },
    }


def collect_elimination_evidence(step_id, method_results):
    from ..math_kernel.constraint_elimination import replay_elimination
    from ..math_kernel.derivation_math import parse_derivation
    from ..math_kernel.expression_parser import (
        parse_math_expression,
        parse_math_relation,
    )
    from ..math_kernel.expression_rewrite import _legacy_tree, tree_latex
    from ..math_kernel.inequality_evidence import target_context

    result = []
    for method in method_results:
        if method.method_id != "eliminate_by_constraint":
            continue
        if len(method.trace_fragments) != 1:
            raise ValueError("elimination teaching trace missing")
        trace = method.trace_fragments[0]
        target, evidence = trace["source_target"], trace["evidence"]
        replay_elimination(target, evidence)
        context, _ = target_context(target)

        def expression(text, symbols=context.symbols):
            return tree_latex(_legacy_tree(parse_math_expression(text, symbols).ast))

        def relation(text, symbols=context.symbols):
            parsed = parse_math_relation(text, symbols)
            a, b = parsed.ast.children
            op = {">=": r"\geq ", "<=": r"\leq ", "!=": r"\ne "}.get(
                parsed.ast.op, parsed.ast.op
            )
            return tree_latex(_legacy_tree(a)) + op + tree_latex(_legacy_tree(b))

        def is_identity(text):
            parsed = parse_math_relation(text, context.symbols)
            if parsed.ast.op != "=":
                return False
            a, b = parsed.ast.children
            # Display only: domain and substitution were already replayed above.
            # Keep the full conditions in execution and public evidence.
            values = [
                parse_math_expression(parsed.source[slice(*n.span)], context.symbols)
                .to_sympy(context.symbols)
                for n in (a, b)
            ]
            return sp.cancel(values[0] - values[1]) == 0

        data = {
            "kind": "verified_constraint_elimination",
            "source": expression(target["target_math"]),
            "result": expression(evidence["expression"]),
            "restoration": relation(evidence["restoration"]),
            "eliminated_variable": evidence["eliminated_variable"],
            "conditions": [relation(c["math"]) for c in target["source_conditions"]],
            "relations": [
                relation(r.parsed.source)
                for r in parse_derivation(
                    evidence["parameters"]["steps"], context.symbols
                )
            ],
            "remaining_conditions": [
                relation(s) for s in evidence["remaining_conditions"]
            ],
            "display_remaining_conditions": [
                relation(s) for s in evidence["remaining_conditions"] if not is_identity(s)
            ],
            "origins": deepcopy(evidence["origins"]),
        }
        result.append(
            EliminationTeachingEvidence(step_id, json.dumps(data, sort_keys=True))
        )
    return tuple(result)
