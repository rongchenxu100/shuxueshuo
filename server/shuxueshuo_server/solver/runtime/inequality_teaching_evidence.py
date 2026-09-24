"""Public mathematical projection of successful inequality Method execution.

Certificates remain in the runtime audit. This adapter reads verified ASTs;
it neither searches for a proof nor solves an equality condition.
"""

import hashlib
import json
from dataclasses import dataclass

import sympy as sp

from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.expression_parser import (
    parse_math_expression,
    parse_math_relation,
)
from shuxueshuo_server.solver.student_display import student_math_display

CONTRACT = "inequality-teaching-evidence/v1"
METHODS = {"apply_two_term_amgm", "close_equality_and_restore"}


def inequality_teaching_evidence_schema():
    return {
        "type": "object",
        "required": ["schema_version", "step_id", "method_id", "data", "evidence_id"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": CONTRACT},
            "step_id": {"type": "string", "minLength": 1},
            "method_id": {"enum": sorted(METHODS)},
            "data": {"type": "object"},
            "evidence_id": {"type": "string", "minLength": 1},
        },
    }


@dataclass(frozen=True)
class InequalityTeachingEvidence:
    step_id: str
    method_id: str
    data_json: str

    def __post_init__(self):
        if not self.step_id or self.method_id not in METHODS:
            raise ValueError("invalid inequality teaching evidence identity")
        data = json.loads(self.data_json)
        required = {
            "target",
            "conditions",
            "terms",
            "fixed_condition",
            "derivation",
            "bound",
            "equality",
            "origins",
        }
        if (
            not required <= data.keys()
            or len(data["terms"]) != 2
            or not data["derivation"]
        ):
            raise ValueError("incomplete inequality teaching evidence")

    @property
    def data(self):
        return json.loads(self.data_json)

    @property
    def evidence_id(self):
        return (
            "inequality:"
            + hashlib.sha256(
                json.dumps(
                    self.to_payload(include_id=False),
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
        )

    def to_payload(self, *, include_id=True):
        value = {
            "schema_version": CONTRACT,
            "step_id": self.step_id,
            "method_id": self.method_id,
            "data": self.data,
        }
        if include_id:
            value["evidence_id"] = self.evidence_id
        return value

    def authority_payload(self):
        return self.to_payload()

    @property
    def schema_version(self):
        return CONTRACT

    @classmethod
    def from_payload(cls, raw):
        if (
            set(raw)
            != {"schema_version", "step_id", "method_id", "data", "evidence_id"}
            or raw["schema_version"] != CONTRACT
        ):
            raise ValueError("invalid inequality teaching evidence payload")
        item = cls(
            raw["step_id"],
            raw["method_id"],
            json.dumps(raw["data"], ensure_ascii=False, sort_keys=True),
        )
        if item.evidence_id != raw["evidence_id"]:
            raise ValueError("inequality teaching evidence hash drift")
        return item


def collect_inequality_evidence(step_id, method_results):
    result = []
    for method in method_results:
        if method.method_id not in METHODS:
            continue
        fragments = method.trace_fragments
        if len(fragments) != 1:
            raise ValueError("inequality teaching evidence missing")
        fragment = fragments[0]
        target, evidence = fragment["source_target"], fragment["evidence"]
        bound = (
            evidence if method.method_id == "apply_two_term_amgm" else evidence["bound"]
        )
        symbols = {
            name: sp.Symbol(name, real=True) for name in target["scalar_symbols"]
        }

        def scalar(source, symbols=symbols):
            return parse_math_expression(source, symbols).to_sympy(symbols)

        def display(source):
            return student_math_display(scalar(source))

        def relation(parsed):
            left, right = parsed.ast.children
            a = scalar(parsed.source[left.span[0] : left.span[1]])
            b = scalar(parsed.source[right.span[0] : right.span[1]])
            op = {">=": "≥", "<=": "≤", "!=": "≠"}.get(parsed.ast.op, parsed.ast.op)
            return f"{student_math_display(a)} {op} {student_math_display(b)}"

        chain = parse_derivation(bound["steps"], symbols)
        # The verified equality identifies the actual AM-GM pair selected by M11.
        # Do not choose an arbitrary sum/root relation from the submitted chain.
        equality = parse_math_relation(bound["equality"], symbols)
        terms = [
            scalar(equality.source[n.span[0] : n.span[1]])
            for n in equality.ast.children
        ]
        conditions = [
            parse_math_relation(item["math"], symbols)
            for item in target["source_conditions"]
        ]
        fixed = None
        fixed_value = None
        for condition in conditions:
            if condition.ast.op != "=":
                continue
            a, b = (
                scalar(condition.source[n.span[0] : n.span[1]])
                for n in condition.ast.children
            )
            if (
                a == sum(terms)
                and not b.free_symbols
                or b == sum(terms)
                and not a.free_symbols
            ):
                fixed = condition
                fixed_value = b if a == sum(terms) else a
                break
        if fixed is None:
            raise ValueError("verified fixed-sum teaching condition missing")

        def select_role(left, right, *, required=False, chain=chain):
            # Match a normalized >= relation using already parsed scalar identities.
            # This is syntax/role classification, never a new proof or substitution.
            matches = []
            for row in chain:
                parsed = row.parsed
                if parsed.ast.op not in {">=", "<="}:
                    continue
                lhs, rhs = (
                    scalar(parsed.source[n.span[0] : n.span[1]])
                    for n in parsed.ast.children
                )
                if parsed.ast.op == "<=":
                    lhs, rhs = rhs, lhs
                if lhs == left and rhs == right:
                    matches.append(row)
            if not matches:
                if required:
                    raise ValueError("verified AM-GM teaching role missing")
                return None
            return {
                "math": relation(matches[0].parsed),
                "origins": [row.origin for row in matches],
            }

        root = sp.sqrt(terms[0] * terms[1])
        application_roles = {
            "amgm": select_role(sum(terms), 2 * root, required=True),
            "bound": select_role(
                scalar(bound["bound"]), scalar(target["target_math"]), required=True
            ),
        }
        for role, lhs, rhs in (
            ("fixed_sum_substitution", fixed_value, 2 * root),
            ("root_bound", fixed_value / 2, root),
        ):
            selected = select_role(lhs, rhs)
            if selected is not None:
                application_roles[role] = selected
        data = {
            "target": display(target["target_math"]),
            "conditions": [relation(c) for c in conditions],
            "terms": [student_math_display(t) for t in terms],
            "fixed_condition": relation(fixed),
            "derivation": [relation(r.parsed) for r in chain],
            "bound": display(bound["bound"]),
            "equality": relation(parse_math_relation(bound["equality"], symbols)),
            "origins": [r.origin for r in chain],
            "application_roles": application_roles,
        }
        if method.method_id == "close_equality_and_restore":
            rows = parse_derivation(evidence["steps"], symbols)
            data.update(
                witness={
                    name: display(value)
                    for name, value in evidence["assignments"].items()
                },
                witness_derivation=[relation(r.parsed) for r in rows],
                witness_origins=[r.origin for r in rows],
                claim_scope="submitted_witness",
                exhaustive=False,
            )
        result.append(
            InequalityTeachingEvidence(
                step_id,
                method.method_id,
                json.dumps(data, ensure_ascii=False, sort_keys=True),
            )
        )
    return tuple(result)
